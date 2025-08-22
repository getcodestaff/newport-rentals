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
    logging.info(f"Agent received job: {ctx.job.id} for room {ctx.room.name}")
    
    session_ended = asyncio.Event()
    greeting_allowed = asyncio.Event()

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track: rtc.Track, publication: rtc.TrackPublication, participant: rtc.RemoteParticipant):
        if track.kind == rtc.TrackKind.KIND_AUDIO and not participant.identity.startswith("chat-to-form-agent"):
            logging.info("AGENT: User audio track subscribed. Allowing greeting.")
            greeting_allowed.set()

    @ctx.room.on("participant_disconnected")
    def on_participant_disconnected(participant):
        logging.info(f"Participant disconnected: {participant.identity}, closing session.")
        session_ended.set()

    try:
        # 1. Build the instructions from the local prompt.template and .env file
        with open("prompt.template", "r") as f:
            prompt_template = Template(f.read())
        
        # Customize instructions based on room name
        room_name = ctx.room.name
        logging.info(f"Room name: {room_name}")
        if "newport" in room_name.lower():
            # Regina's personality for Newport Beach calls - FULL DETAILED PROMPT
            instructions = (
                f"Role: You are 'Regina,' a friendly and welcoming Guest Experience Concierge with Newport Beach Vacation Properties. You are the guest's first personal touchpoint after booking. "
                f"Prime Directive: Your goal is not just to confirm details, but to make the guest feel genuinely welcomed and excited about their upcoming trip. Every interaction should build confidence and anticipation, ensuring they feel cared for and that their vacation is in great hands. A successful call leaves the guest feeling reassured and delighted. "
                f"Tone: Warm, relaxed, welcoming, and reassuring. You're not a call center agent; you're a helpful local guide setting the stage for a wonderful stay. "
                f"Optimized Conversational Flow & Persuasion Sequence: "
                f"1. The Greeting (Warm Pattern Interrupt): Goal: Immediately establish a warm, positive context. Avoid the 'Is now a good time?' trope which invites a 'no.' Assume they're happy to hear from you because you're confirming their vacation. "
                f"Script: 'Hi, is this [Guest Name]?' (Pause for confirmation) 'Wonderful! This is Regina calling from Newport Beach Vacation Properties. I'm just calling to get you all set for your upcoming trip—it looks like you're all booked for the [Property Name] home starting [Date]. We're so excited to have you.' "
                f"2. The 'Quick Confirmation' (Low Cognitive Load): Goal: Group the necessary data collection into a single, smooth, and easy step. Frame the 'recorded line' part as a simple necessity for their benefit. "
                f"Script: 'I just have two quick things to confirm for the reservation, and I do have to let you know this line is recorded for accuracy. First, can I just get a quick confirmation that you're over the age of 26?' (Pause for response) 'Perfect, thank you. And just so we can prepare the home perfectly for you, can you tell me how many adults and children will be in your group?' "
                f"3. Setting Expectations (Framed as Helpful Tips): Goal: Deliver key information not as a list of instructions, but as helpful insider tips for a seamless stay. This manages cognitive load by chunking related information. "
                f"Script: 'Great, thank you for that. Now for the fun part. I just want to quickly walk you through how we'll get you all your info.' (Pause) 'You'll see two important emails from us shortly. The first is your rental agreement, which you can sign electronically. The second is your personal Guest Portal link—that's your go-to spot for everything, from the Wi-Fi password to local recommendations.' (Pause) 'Then, about a day before you arrive, you'll get a welcome text from our on-site care team. That text thread becomes your direct line to us for anything you need during your stay. It's the best and fastest way to reach us, especially after hours.' "
                f"4. The Closing (Reinforce Value & Openness): Goal: End on a high note, reinforcing that you're available and excited for their arrival. "
                f"Script: 'And that's everything! We handle the rest. We're really looking forward to hosting you. Is there anything at all I can answer for you right now?' (Handle any questions) 'Alright. Well, if you think of anything else, our main Vacation Planner line is 949-270-1119. Thanks again for choosing us, [Guest Name], and get ready for a fantastic time in Newport Beach!' "
                f"Mandatory Constraints: Human Rhythm: Break up your sentences and pause for guest responses. Never deliver more than two or three sentences in a row without a natural pause. One Question at a Time: Stick to asking one simple question at a time to keep the conversation easy and flowing. Positive Framing: Always frame information in a positive, helpful light (e.g., 'to prepare the home perfectly for you' instead of 'I need to know how many people'). Avoid Jargon: Use simple, welcoming language ('on-site care team' instead of 'operations team,' 'get you all set' instead of 'confirm your reservation')."
            )
        else:
            # Default instructions using template
            instructions = prompt_template.substitute(
                business_name=os.getenv("BUSINESS_NAME", "Voice Sell AI"),
                knowledge_base=os.getenv("KNOWLEDGE_BASE", "VoiceSell provides AI solutions for sales and customer service.")
            )

        await ctx.connect()
        logging.info("Agent connected to the room.")

        # All model initialization and session logic is now safely inside the try block
        logging.info("🔧 Starting model initialization...")
        stt = deepgram.STT()
        logging.info("✅ STT (Deepgram) initialized successfully")
        
        # Use OpenAI GPT-4 for reliable performance  
        llm = openai.LLM(model="gpt-4o")
        
        # Use the pre-warmed VAD model from userdata
        vad = ctx.proc.userdata["vad"]
        
        # Use the same TTS client for all sessions
        tts = ctx.proc.userdata["tts_default"]
        if tts is None:
            logging.error("TTS is not available - agent will not be able to speak")
            logging.error("Please check your Cartesia API key or add credits to your account")
            # Create session without TTS - agent will still process but won't speak
            session = agents.AgentSession(
                stt=stt,
                llm=llm,
                tts=None,  # No TTS available
                vad=vad,
                turn_detection="vad",  # Use the simpler, faster, and stable VAD-based turn detection
                user_away_timeout=60,  # Wait for 60 seconds of silence before ending
            )
        else:
            logging.info("Using sonic-english voice for this session")
            session = agents.AgentSession(
                stt=stt,
                llm=llm,
                tts=tts,
                vad=vad,
                turn_detection="vad",  # Use the simpler, faster, and stable VAD-based turn detection
                user_away_timeout=60,  # Wait for 60 seconds of silence before ending
            )
        logging.info(f"Using instructions: {instructions[:200]}...")
        agent = BusinessAgent(instructions=instructions)

        @session.on("user_state_changed")
        def on_user_state_changed(ev: UserStateChangedEvent):
            if ev.new_state == "away" and agent._is_form_displayed:
                logging.info("User is viewing the form, ignoring away state.")
                return
            if ev.new_state == "away":
                logging.info("User is away and no form is displayed, closing session.")
                session_ended.set()

        async def submit_lead_form_handler(data: rtc.RpcInvocationData):
            session.interrupt()
            logging.info(f"Agent received submit_lead_form RPC with payload: {data.payload}")

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
        
        @session.on("user_speech_committed")
        def on_user_speech_committed(ev):
            logging.info(f"User said: {ev.user_transcript}")
            
        @session.on("agent_speech_committed") 
        def on_agent_speech_committed(ev):
            logging.info(f"Agent said: {ev.agent_transcript}")
        ctx.room.local_participant.register_rpc_method("submit_lead_form", submit_lead_form_handler)
        
        # Start talking immediately without waiting for user audio track
        room_name = ctx.room.name
        
        # Log which agent identity we're using
        if "newport" in room_name.lower():
            logging.info("Agent running as newport-rentals")
            logging.info("Using Regina's personality for Newport Beach Vacation Properties")
            if tts is not None:
                logging.info("About to speak greeting...")
                await session.say(f"Hi, is this the guest calling about your Newport Beach reservation?", allow_interruptions=True)
                logging.info("Greeting spoken successfully")
            else:
                logging.error("Cannot speak - TTS is not available")
        else:
            logging.info("Agent running as voice-sell-agent")
            logging.info("Using Voice Sell AI personality for this session")
            if tts is not None:
                await session.say(f"Thank you for calling Voice Sell AI. How can I help you today?", allow_interruptions=True)
            else:
                logging.error("Cannot speak - TTS is not available")

        await session_ended.wait()
        await session.aclose()

    except Exception as e:
        logging.error(f"An unhandled error occurred in the entrypoint: {e}", exc_info=True)
    finally:
        ctx.shutdown()

async def request_fnc(req: JobRequest):
    logging.info("="*50)
    logging.info(f"🔥 JOB REQUEST RECEIVED! ID: {req.job.id}")
    logging.info(f"🔥 Room: {req.job.room}")
    logging.info(f"🔥 Job Type: {type(req.job)}")
    logging.info("="*50)
    
    try:
        # Accept ALL jobs for now to debug  
        logging.info(f"✅ ACCEPTING job {req.job.id} for room {req.job.room}")
        await req.accept(identity="newport-rentals")
        logging.info(f"🎉 SUCCESSFULLY ACCEPTED job {req.job.id}")
    except Exception as e:
        logging.error(f"❌ FAILED to accept job {req.job.id}: {e}")
        raise

def prewarm(proc: agents.JobProcess):
    # This function is called once when a new job process starts.
    # We load environment variables and our stable, local VAD model here.
    load_dotenv()
    logging.info("Prewarm: Environment variables loaded into child process.")
    
    proc.userdata["vad"] = silero.VAD.load()
    logging.info("Prewarm complete: VAD model loaded.")
    
    # Initialize TTS configuration with error handling
    try:
        proc.userdata["tts_default"] = cartesia.TTS(model="sonic-english")
        logging.info("TTS created successfully")
        logging.info("Prewarm complete: Cartesia TTS client initialized.")
    except Exception as e:
        logging.error(f"Failed to initialize Cartesia TTS: {e}")
        logging.warning("TTS will not be available - agent will not be able to speak")
        proc.userdata["tts_default"] = None



if __name__ == "__main__":
    import sys
    
    # Check for command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "download-files":
        logging.info("Downloading model files...")
        # This is called during Docker build to pre-download models
        exit(0)
    
    logging.info("Starting Newport Beach Agent Worker...")
    
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
    

    

    
    # Run the agent (same for both local and Render)
    logging.info("About to start agents.cli.run_app...")
    logging.info(f"Agent will register with name: newport-rentals")
    try:
        agents.cli.run_app(
            agents.WorkerOptions(
                request_fnc=request_fnc,
                entrypoint_fnc=entrypoint,
                prewarm_fnc=prewarm,
                agent_name="newport-rentals"
            )
        )
        logging.info("agents.cli.run_app completed successfully")
    except Exception as e:
        logging.error(f"agents.cli.run_app failed with error: {e}")
        raise

