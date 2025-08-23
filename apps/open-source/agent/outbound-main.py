import asyncio
import logging
import os
import aiohttp
import json
import threading
from string import Template
from dotenv import load_dotenv

# Load environment variables from the .env file in this directory
load_dotenv()


from core_agent import BusinessAgent
from livekit import agents, rtc
from livekit.agents import JobRequest, UserStateChangedEvent
from livekit.agents import tts
from livekit.plugins import deepgram, openai, silero, cartesia

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Get configuration from environment variables
WEBHOOK_URL = os.getenv("WEBHOOK_URL")



async def entrypoint(ctx: agents.JobContext):
    logging.info(f"Outbound Agent received job: {ctx.job.id} for room {ctx.room.name}")
    
    session_ended = asyncio.Event()

    @ctx.room.on("participant_disconnected")
    def on_participant_disconnected(participant):
        logging.info(f"Participant disconnected: {participant.identity}, closing session.")
        session_ended.set()

    try:
        # Build the instructions from the outbound prompt template
        with open("outbound-prompt.template", "r") as f:
            outbound_template = Template(f.read())
        
        # Use the outbound Ashley personality for all rooms handled by this agent
        room_name = ctx.room.name
        logging.info(f"Outbound room name: {room_name}")
        
        instructions = outbound_template.substitute(
            business_name=os.getenv("BUSINESS_NAME", "Devin Mallonee"),
            knowledge_base=os.getenv("KNOWLEDGE_BASE", "Devin is a Web and Software Developer building AI solutions.")
        )

        await ctx.connect()
        logging.info("Outbound agent connected to the room.")

        # All model initialization and session logic is now safely inside the try block
        logging.info("🔧 Starting outbound model initialization...")
        stt = deepgram.STT()
        logging.info("✅ STT (Deepgram) initialized successfully")
        
        # Use OpenAI GPT-4 for reliable performance  
        llm = openai.LLM(model="gpt-4o")
        
        # Use the pre-warmed VAD model from userdata
        vad = ctx.proc.userdata["vad"]
        
        # Use the same TTS client for all sessions
        tts = ctx.proc.userdata["tts_default"]
        if tts is None:
            logging.error("TTS is not available - outbound agent will not be able to speak")
            logging.error("Please check your Cartesia API key or add credits to your account")
            # Create session without TTS - agent will still process but won't speak
            session = agents.AgentSession(
                stt=stt,
                llm=llm,
                tts=None,  # No TTS available
                vad=vad,
                turn_detection="vad",  # Use the simpler, faster, and stable VAD-based turn detection
                user_away_timeout=120,  # Longer timeout for outbound calls
            )
        else:
            logging.info("Using sonic-english voice for outbound session")
            session = agents.AgentSession(
                stt=stt,
                llm=llm,
                tts=tts,
                vad=vad,
                turn_detection="vad",  # Use the simpler, faster, and stable VAD-based turn detection
                user_away_timeout=120,  # Longer timeout for outbound calls
            )
        logging.info(f"Using outbound instructions: {instructions[:200]}...")
        agent = BusinessAgent(instructions=instructions)

        @session.on("user_state_changed")
        def on_user_state_changed(ev: UserStateChangedEvent):
            if ev.new_state == "away" and agent._is_form_displayed:
                logging.info("User is viewing the form, ignoring away state.")
                return
            if ev.new_state == "away":
                logging.info("User is away and no form is displayed, closing outbound session.")
                session_ended.set()

        async def submit_lead_form_handler(data: rtc.RpcInvocationData):
            session.interrupt()
            logging.info(f"Outbound agent received submit_lead_form RPC with payload: {data.payload}")

            async def _process_submission():
                if not WEBHOOK_URL:
                    logging.error("WEBHOOK_URL is not set in the .env file. Cannot send lead.")
                    await session.say("I'm sorry, there is a configuration error and I can't save your information.")
                    return

                try:
                    agent._is_form_displayed = False
                    lead_data = json.loads(data.payload)
                    
                    async with aiohttp.ClientSession() as http_session:
                        headers = {"Content-Type": "application/json"}
                        async with http_session.post(WEBHOOK_URL, headers=headers, json=lead_data) as response:
                            if 200 <= response.status < 300:
                                logging.info(f"Successfully sent lead data to webhook: {WEBHOOK_URL}")
                                await session.say(
                                    "Thank you. Your information has been sent. Was there anything else I can help you with today?",
                                    allow_interruptions=True
                                )
                            else:
                                logging.error(f"Failed to send lead to webhook. Status: {response.status}")
                                await session.say("I'm sorry, there was an error sending your information.")
                except Exception as e:
                    logging.error(f"Error processing submit_lead_form RPC for webhook: {e}")
                    await session.say("I'm sorry, a technical error occurred.")

            asyncio.create_task(_process_submission())
            return "SUCCESS"

        await session.start(room=ctx.room, agent=agent)
        ctx.room.local_participant.register_rpc_method("submit_lead_form", submit_lead_form_handler)
        
        logging.info("Outbound agent running as ashley-outbound")
        logging.info("Using Ashley's personality for vacation rental lead follow-up")
        
        # IMMEDIATE OUTBOUND GREETING - Start talking right away
        logging.info("Starting outbound call with proactive greeting")
        await asyncio.sleep(3)  # Wait for connection to stabilize
        await session.say(
            "Hi, is this the right number I'm calling? This is Ashley calling from Newport Beach Vacation Properties. I hope I'm not catching you at a bad time? I'm following up because you showed interest in booking one of our beautiful Newport Beach vacation homes. Do you have a few minutes to chat about your upcoming trip?",
            allow_interruptions=True
        )

        await session_ended.wait()
        await session.aclose()

    except Exception as e:
        logging.error(f"An unhandled error occurred in the outbound entrypoint: {e}", exc_info=True)
    finally:
        ctx.shutdown()

async def request_fnc(req: JobRequest):
    logging.info("="*50)
    logging.info(f"🔥 OUTBOUND JOB REQUEST RECEIVED! ID: {req.job.id}")
    logging.info(f"🔥 Room: {req.job.room}")
    logging.info(f"🔥 Job Type: {type(req.job)}")
    logging.info("="*50)
    
    try:
        # Only accept outbound jobs
        room_name = req.job.room
        if "outbound" in room_name.lower():
            logging.info(f"✅ ACCEPTING outbound job {req.job.id} for room {req.job.room}")
            await req.accept(identity="ashley-outbound")
            logging.info(f"🎉 SUCCESSFULLY ACCEPTED outbound job {req.job.id}")
        else:
            logging.info(f"🚫 REJECTING non-outbound job {req.job.id} for room {req.job.room}")
            await req.reject()
    except Exception as e:
        logging.error(f"❌ FAILED to process job {req.job.id}: {e}")
        raise

def prewarm(proc: agents.JobProcess):
    # This function is called once when a new job process starts.
    # We load environment variables and our stable, local VAD model here.
    load_dotenv()
    logging.info("Outbound Prewarm: Environment variables loaded into child process.")
    
    proc.userdata["vad"] = silero.VAD.load()
    logging.info("Outbound Prewarm complete: VAD model loaded.")
    
    # Initialize TTS configuration with error handling
    try:
        proc.userdata["tts_default"] = cartesia.TTS(model="sonic-english")
        logging.info("Outbound TTS created successfully")
        logging.info("Outbound Prewarm complete: Cartesia TTS client initialized.")
    except Exception as e:
        logging.error(f"Failed to initialize Cartesia TTS for outbound: {e}")
        logging.warning("TTS will not be available - outbound agent will not be able to speak")
        proc.userdata["tts_default"] = None



if __name__ == "__main__":
    import sys
    
    # Check for command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "download-files":
        logging.info("Downloading model files for outbound agent...")
        # This is called during Docker build to pre-download models
        exit(0)
    
    logging.info("Starting Ashley Outbound Agent Worker...")
    
    # Debug: Log environment variables for LiveKit connection
    livekit_url = os.getenv("LIVEKIT_URL")
    livekit_api_key = os.getenv("LIVEKIT_API_KEY")
    livekit_api_secret = os.getenv("LIVEKIT_API_SECRET")
    
    logging.info(f"LiveKit URL: {livekit_url}")
    logging.info(f"LiveKit API Key: {'***' if livekit_api_key else 'NOT SET'}")
    logging.info(f"LiveKit API Secret: {'***' if livekit_api_secret else 'NOT SET'}")
    
    if not livekit_url or not livekit_api_key or not livekit_api_secret:
        logging.error("Missing required LiveKit environment variables!")
        logging.error("Please set LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET")
        exit(1)
    
    # Run the outbound agent
    logging.info("About to start outbound agents.cli.run_app...")
    logging.info(f"Outbound agent will register with name: ashley-outbound")
    try:
        agents.cli.run_app(
            agents.WorkerOptions(
                request_fnc=request_fnc,
                entrypoint_fnc=entrypoint,
                prewarm_fnc=prewarm,
                agent_name="ashley-outbound"
            )
        )
        logging.info("Outbound agents.cli.run_app completed successfully")
    except Exception as e:
        logging.error(f"Outbound agents.cli.run_app failed with error: {e}")
        raise