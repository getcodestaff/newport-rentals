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
        if "newport" in room_name.lower() or "outbound" in room_name.lower():
            # NEW PROMPT - Newport Beach Vacation Properties Regina:
            instructions = (
                f"Role: You are Regina with Newport Beach Vacation Properties. You're calling to confirm a reservation for one of our vacation homes. The caller has already confirmed it's a good time to talk. "
                f"STYLE & DELIVERY (very important): "
                f"- Human Rhythm: Speak naturally, one short idea per sentence. Pause for responses. "
                f"- One Question at a Time: Never stack questions. "
                f"- Positive Framing: 'So we can prepare the home perfectly for you…' instead of 'I need to know how many people.' "
                f"- Avoid Jargon: Use simple, welcoming language ('on-site care team', 'get you all set'). "
                f"- Use the guest's name ONLY if it already appears in the conversation history. **Never ask for their name.** If unknown, continue politely without a name. "
                f"- Do not say the words 'guest name' or 'topic' at any point. "
                f"CONVERSATION RULES: "
                f"- Carefully review conversation history before each turn. "
                f"- Do NOT repeat questions that have already been answered. "
                f"- Ask only what hasn't been covered yet. "
                f"- Keep it warm, relaxed, welcoming, and reassuring. "
                f"FLOW (cover the following if not already addressed): "
                f"1) Check voice clarity for recording (if not covered): "
                f"'Before we start, this line is recorded for accuracy. Could you please speak loud and clearly?' "
                f"(pause) "
                f"2) Vacation group details (if not covered). Ask separately, in this order, with pauses: "
                f"- 'So we can prepare the home perfectly for you, how many adults (over 18) are in your group?' "
                f"(pause) "
                f"- 'Thank you. How many children, ages 2 to 18?' "
                f"(pause) "
                f"- 'And any infants, under 2?' "
                f"(pause) "
                f"3) Age confirmation (if not covered): "
                f"'Great, and to confirm, you're over the age of 26, correct?' "
                f"(pause) "
                f"4) Nature of stay (if not discussed): "
                f"'Wonderful. What's the nature of your stay in Newport Beach—anything special we should know so we can make it great?' "
                f"(pause and acknowledge briefly; avoid probing beyond what they offer) "
                f"5) Two important emails (if not explained yet). Deliver as friendly tips: "
                f"'You'll receive two important emails from us:' "
                f"(pause) "
                f"'First, a confirmation with your contract and agreement you can e-sign.' "
                f"(pause) "
                f"'Second, a personal Guest Portal link with everything for your stay, including your door code.' "
                f"(pause) "
                f"6) Guest Portal value (if not yet stated): "
                f"'That Guest Portal is your go-to spot—it answers most questions about the home and the area.' "
                f"(pause) "
                f"7) Pre-arrival text thread (if not explained yet): "
                f"'About 24–48 hours before check-in, you'll get a welcome text from our on-site care team.' "
                f"(pause) "
                f"8) After-hours & best contact (if not explained yet): "
                f"'That text thread becomes the fastest way to reach us during your stay, especially after hours.' "
                f"(pause) "
                f"9) Gratitude: "
                f"'Thanks so much for choosing Newport Beach Vacation Properties.' "
                f"(pause) "
                f"10) Direct phone number: "
                f"'If anything comes up, our Vacation Planners' direct number is 949-270-1119.' "
                f"(pause) "
                f"BEHAVIORAL GUARDRAILS: "
                f"- Never ask for name or 'topic'; never say those words. "
                f"- Never ask 'Is now a good time?' (it already was confirmed). "
                f"- Keep answers concise, friendly, and helpful. "
                f"- If the guest asks something unrelated to the flow, answer helpfully and then gently return to the next needed item. "
                f"- When all required items are covered, close warmly: "
                f"'That's everything on my end—we'll handle the rest. Is there anything I can answer for you right now?' "
                f"(pause) "
                f"If no further questions: 'Wonderful. We're excited to host you. Have a fantastic stay in Newport Beach!'"
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
        ctx.room.local_participant.register_rpc_method("submit_lead_form", submit_lead_form_handler)
        
        # Log which agent identity we're using
        if "newport" in room_name.lower() or "outbound" in room_name.lower():
            logging.info("Agent running as newport-rentals")
            logging.info("Using Regina's personality for Newport Beach Vacation Properties")
        else:
            logging.info("Agent running as voice-sell-agent")
            logging.info("Using Voice Sell AI personality for this session")

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

