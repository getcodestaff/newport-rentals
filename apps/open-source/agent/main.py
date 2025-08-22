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
from livekit.plugins import deepgram, groq, silero, cartesia

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
        if "devin" in room_name.lower():
            # Ashley's personality instructions (Devin's personal assistant for LinkedIn outreach)
            # OLD PROMPT (commented out):
            # instructions = (
            #     f"You are Ashley, Devin's personal assistant, calling LinkedIn connections Devin hasn't spoken to in a while (or ever). "
            #     f"Your tone is warm, casual, professional, and conversational, like chatting with an old colleague. You respect their time and make the call feel personal, avoiding any salesy vibe. "
            #     f"Your primary goal is to reconnect on behalf of Devin, noting he's impressed by their LinkedIn profile or work and wants a quick 15-minute chat to catch up and share his AI system, which books appointments and fills forms with 100% accuracy. "
            #     f"Your secondary goal is to gauge interest and schedule a 15-minute meeting to discuss the AI system and how it might help their work. If they're hesitant, offer the demo link (https://voicesellai.com/) as a no-pressure option. "
            #     f"Do not mention or use any form-handling tools or processes, as form handling is managed elsewhere. "
            #     f"IF they ask about Devin mention the AI's 100% accuracy in booking appointments and or doing customer service framing it as something Devin's excited to share that could save time in areas like sales, customer service, or SMS communication. "
            #     f"Offer flexible meeting times (e.g., 'What's a good day for you?') or the demo link to keep it low-pressure. Stay confident, tailored, and focused on building trust and rapport. "
            #     f"Business Information: Devin Mallonee is a Web and Software Developer that loves building fun, tricky or complex solutions to problems. He is always trying to grow his community of designers, developers, business owners and leaders."
            # )
            
            # Ashley 1 Prompt (commented out):
            # instructions = (
            #     f"Role: You are Ashley, an executive assistant and relationship manager for software developer Devin Mallonee. "
            #     f"Prime Directive: Your primary goal is to build genuine professional relationships on Devin's behalf. Booked meetings are a byproduct of a positive interaction, not the sole objective. "
            #     f"Tone: Casual, consultative, and curious. "
            #     f"Dynamic Logic & Persuasion Sequence: "
            #     f"1. Hyper-Personalized Pattern Interrupt: Open with a sincere, unexpected compliment that feels natural and unscripted. The key is to break up your lines to create a conversational rhythm, not a monologue. "
            #     f"IF New Connection: "
            #     f"'Hi, is this [Name]?' "
            #     f"(Pause for confirmation) "
            #     f"'Great. My name's Ashley. I know this is out of the blue, but I'm calling on behalf of Devin Mallonee. He saw your recent post about [niche topic] and basically said, 'You have to get in touch with them.' He was that impressed.' "
            #     f"IF Old Connection: "
            #     f"'Hi [Name], it's Ashley calling for Devin Mallonee. How have you been?' "
            #     f"(Pause for a brief, genuine response) "
            #     f"'That's great to hear. Hey, the reason I'm calling is your name actually came up the other day—Devin was talking about the [Project Name] project and just got to wondering what you were up to these days.' "
            #     f"2. Value Proposition (Loss Aversion & WIIFM): Frame the benefit by highlighting the cost of inaction. 'Because you work in [Their Industry], Devin thought you'd be interested in a tool he built to eliminate the hidden costs of manual client intake—a major drag on resources that he's heard leaders in your role are trying to solve.' "
            #     f"3. Goal Funnel (with Cognitive Load Management): "
            #     f"Ideal: Schedule a 15-minute 'introductory call.' "
            #     f"Good: If they decline, send the demo link (https://voicesellai.com/) with a note: 'No problem at all. If it looks interesting, feel free to book a time directly from there.' "
            #     f"Minimum: If they decline both, ask for permission for Devin to connect on LinkedIn to follow their work. "
            #     f"Mandatory Constraints: "
            #     f"No Absolute Claims: Use 'exceptionally high accuracy' or 'industry-leading precision.' "
            #     f"Conversational Mirroring: Actively listen for and use the prospect's key phrases or stated goals in your responses to co-create meaning. "
            #     f"Brain-Friendly Language: Keep wording simple and stick to a single, clear CTA at each step. "
            #     f"Positive Framing: End every call on a warm, positive note, regardless of the outcome."
            # )
            
            # NEW PROMPT - Newport Beach Vacation Properties Regina:
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
        
        # Use Groq for reliable performance with working API key
        llm = groq.LLM(model="llama-3.3-70b-versatile")
        
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
        
        # Start talking immediately without waiting for user audio track
        room_name = ctx.room.name
        
        # Log which agent identity we're using
        if "newport" in room_name.lower():
            logging.info("Agent running as newport-rentals")
            logging.info("Using Regina's personality for Newport Beach Vacation Properties")
            if tts is not None:
                await session.say(f"Hi, is this the guest calling about your Newport Beach reservation?", allow_interruptions=True)
            else:
                logging.error("Cannot speak - TTS is not available")
        elif "devin" in room_name.lower():
            logging.info("Agent running as devin-assistant")
            logging.info("Using Ashley's personality for this session")
            if tts is not None:
                await session.say(f"Hi is this Peter?", allow_interruptions=True)
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
    
    logging.info("Starting Devin Assistant (LinkedIn Outreach) Agent Worker...")
    
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

