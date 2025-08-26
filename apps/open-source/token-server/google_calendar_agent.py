import asyncio
import logging
import os
import aiohttp
import json
from datetime import datetime, timedelta
from typing import Dict, Any

from livekit import agents
from livekit.agents import JobRequest, function_tool, WorkerOptions, AgentSession
from livekit import rtc
from livekit.plugins import deepgram, groq, silero, cartesia

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Environment variables
LIVEKIT_URL = os.getenv("LIVEKIT_URL")
CALENDAR_API_URL = os.getenv("CALENDAR_API_URL", "https://newport-rentals.onrender.com")

class BookingAgent:
    """Newport Beach Rental Agent with Calendar Booking Capabilities"""
    
    def __init__(self, instructions: str):
        self.instructions = instructions
        self._session = None
        
    @function_tool
    async def check_calendar_availability(self, date: str, duration: int = 60) -> str:
        """
        Check available appointment slots for property viewings.
        
        Args:
            date: Date in YYYY-MM-DD format (e.g., "2024-08-27")
            duration: Appointment duration in minutes (default 60)
        
        Returns:
            String describing available time slots or unavailability
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{CALENDAR_API_URL}/api/agent/check-availability"
                payload = {"date": date, "duration": duration}
                
                async with session.post(url, json=payload, timeout=10.0) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success"):
                            available_times = data.get("available_times", [])
                            if available_times:
                                times_str = ", ".join(available_times[:4])  # Limit to 4 options
                                return f"I have these times available on {date}: {times_str}. Which time works best for you?"
                            else:
                                return f"I don't have any available appointment slots on {date}. Let me suggest some other dates that might work."
                        else:
                            return data.get("message", "I'm having trouble checking availability right now.")
                    else:
                        return "I'm experiencing technical difficulties checking the calendar. Please try again in a moment."
                        
        except Exception as e:
            logging.error(f"Error checking calendar availability: {e}")
            return "I'm having trouble accessing the calendar system right now. Would you like to try a different date?"

    @function_tool  
    async def book_property_viewing(
        self, 
        guest_name: str, 
        guest_phone: str, 
        date: str, 
        time: str,
        guest_email: str = "",
        notes: str = ""
    ) -> str:
        """
        Book a property viewing appointment.
        
        Args:
            guest_name: Full name of the guest
            guest_phone: Phone number of the guest  
            date: Date in YYYY-MM-DD format
            time: Time in format like "2:00 PM" or "14:00"
            guest_email: Optional email address
            notes: Optional appointment notes
        
        Returns:
            Confirmation message for the booking
        """
        try:
            # Convert time to ISO format
            date_obj = datetime.strptime(date, "%Y-%m-%d")
            
            # Parse time (handle both "2:00 PM" and "14:00" formats)
            try:
                if "AM" in time or "PM" in time:
                    time_obj = datetime.strptime(time, "%I:%M %p").time()
                else:
                    time_obj = datetime.strptime(time, "%H:%M").time()
            except:
                # Fallback: try to parse just hour
                hour = int(time.split(":")[0]) if ":" in time else int(time)
                time_obj = datetime.min.time().replace(hour=hour)
            
            start_datetime = datetime.combine(date_obj, time_obj)
            end_datetime = start_datetime + timedelta(hours=1)  # 1 hour appointment
            
            # Convert to ISO format with timezone
            start_iso = start_datetime.isoformat() + "-07:00"  # Pacific time
            end_iso = end_datetime.isoformat() + "-07:00"
            
            async with aiohttp.ClientSession() as session:
                url = f"{CALENDAR_API_URL}/api/agent/book-appointment"
                payload = {
                    "guest_name": guest_name,
                    "guest_phone": guest_phone,
                    "guest_email": guest_email,
                    "start_time": start_iso,
                    "end_time": end_iso,
                    "description": f"Property viewing appointment. {notes}".strip()
                }
                
                async with session.post(url, json=payload, timeout=10.0) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success"):
                            formatted_time = start_datetime.strftime("%A, %B %d at %I:%M %p")
                            confirmation_msg = f"Perfect! I've booked your property viewing appointment for {formatted_time}. "
                            if guest_email:
                                confirmation_msg += "You'll receive a calendar invitation with all the details. "
                            confirmation_msg += "We'll see you then! Is there anything else I can help you with?"
                            return confirmation_msg
                        else:
                            return data.get("message", "I wasn't able to book that appointment. The time slot might no longer be available.")
                    else:
                        return "I'm having trouble booking the appointment right now. Please try again in a moment."
                        
        except Exception as e:
            logging.error(f"Error booking appointment: {e}")
            return "I encountered an error while booking your appointment. Let me try again or suggest a different time."

    @function_tool
    async def get_available_dates(self) -> str:
        """
        Get upcoming available dates for property viewings.
        
        Returns:
            String listing available dates for booking
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{CALENDAR_API_URL}/api/agent/available-dates"
                
                async with session.get(url, timeout=10.0) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success"):
                            dates = data.get("available_dates", [])
                            if dates:
                                date_strings = [date["display"] for date in dates[:5]]  # Limit to 5 dates
                                dates_list = ", ".join(date_strings)
                                return f"Here are the upcoming dates available for property viewings: {dates_list}. Which date interests you?"
                            else:
                                return "I don't have any available dates in the near future. Let me check with management and get back to you."
                        else:
                            return "I'm having trouble getting available dates right now."
                    else:
                        return "I'm experiencing technical difficulties. Please try again shortly."
                        
        except Exception as e:
            logging.error(f"Error getting available dates: {e}")
            return "I'm having trouble accessing the calendar system. Would you like me to take your information and have someone call you back?"


async def entrypoint(ctx: agents.JobContext):
    """Main entry point for the Newport Beach booking agent"""
    logging.info(f"Booking Agent received job: {ctx.job.id} for room {ctx.room.name}")
    
    session_ended = asyncio.Event()
    greeting_allowed = asyncio.Event()

    # Set up event listeners
    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track: rtc.Track, publication: rtc.TrackPublication, participant: rtc.RemoteParticipant):
        if track.kind == rtc.TrackKind.KIND_AUDIO and not participant.identity.startswith("newport-rentals"):
            logging.info("BOOKING AGENT: User audio track subscribed. Allowing greeting.")
            greeting_allowed.set()

    @ctx.room.on("participant_disconnected")
    def on_participant_disconnected(participant):
        logging.info(f"Participant disconnected: {participant.identity}, closing session.")
        session_ended.set()

    try:
        # Connect to the room
        await ctx.connect()
        logging.info("Booking Agent connected to the room.")

        # Agent instructions with calendar booking capabilities
        instructions = """
        You are Regina, the friendly concierge for Newport Beach Vacation Properties. You help guests with information about luxury vacation rentals and can schedule property viewings.

        CALENDAR BOOKING CAPABILITIES:
        When guests ask about scheduling property viewings, seeing properties, or booking appointments:

        1. **Check Availability**: Use check_calendar_availability(date) to see available time slots
        2. **Show Options**: Present available times in a natural, conversational way  
        3. **Collect Information**: Get their full name and phone number (email is optional but helpful)
        4. **Book Appointment**: Use book_property_viewing() to schedule their visit
        5. **Confirm Details**: Provide clear confirmation with date/time

        CONVERSATION FLOW EXAMPLES:
        Guest: "I'd like to see the property"
        You: "I'd be happy to schedule a property viewing for you! What day would work best for you?"

        Guest: "How about tomorrow?" 
        You: [Call check_calendar_availability with tomorrow's date]
        You: "I have these times available tomorrow: [list times]. Which works best for you?"

        Guest: "2 PM sounds perfect"
        You: "Excellent choice! To book your 2 PM appointment, I'll need your full name and phone number."

        Guest: [Provides name and phone]
        You: [Call book_property_viewing with their details]
        You: "Perfect! I've scheduled your viewing for [day] at 2 PM. You'll receive a confirmation."

        IMPORTANT NOTES:
        - Business hours are 9 AM - 6 PM, Monday through Friday
        - Each property viewing is scheduled for 1 hour
        - Always be warm, professional, and helpful
        - If a requested time isn't available, suggest alternatives using get_available_dates()
        - Collect email addresses when possible for calendar invitations
        - Properties are located in beautiful Newport Beach, California

        GENERAL INFORMATION:
        You represent Newport Beach Vacation Properties, offering luxury vacation rentals in Newport Beach, CA. You can answer questions about amenities, locations, pricing, and availability. When guests want to schedule viewings, use your calendar booking tools.
        """

        # Initialize STT, LLM, TTS, VAD
        stt = deepgram.STT()
        llm = groq.LLM(model="llama-3.3-70b-versatile")
        tts = cartesia.TTS(model="sonic-english")
        vad = silero.VAD.load()

        # Create agent session
        session = agents.AgentSession(
            stt=stt,
            llm=llm, 
            tts=tts,
            vad=vad,
            turn_detection="vad",
            user_away_timeout=60
        )

        # Initialize agent with calendar tools
        agent = BookingAgent(instructions=instructions)

        @session.on("user_state_changed")
        def on_user_state_changed(ev):
            if ev.new_state == "away":
                logging.info("User is away, closing session.")
                session_ended.set()

        # Start the agent session
        logging.info("BOOKING AGENT: Starting AgentSession...")
        await session.start(room=ctx.room, agent=agent)
        logging.info("BOOKING AGENT: AgentSession started.")

        try:
            # Wait for user and give greeting
            logging.info("BOOKING AGENT: Waiting for user connection...")
            await asyncio.wait_for(greeting_allowed.wait(), timeout=20.0)
            logging.info("BOOKING AGENT: Sending greeting...")
            await session.say(
                "Hello! Thank you for calling Newport Beach Vacation Properties. I'm Regina, your personal concierge. How can I help you today?", 
                allow_interruptions=True
            )
            logging.info("BOOKING AGENT: Greeting completed.")
        except asyncio.TimeoutError:
            logging.warning("BOOKING AGENT: Timed out waiting for user. No greeting sent.")
            session_ended.set()

        # Keep session alive
        await session_ended.wait()
        await session.aclose()

    except Exception as e:
        logging.error(f"Booking Agent error: {e}")
        ctx.shutdown()
        return

    ctx.shutdown()


async def request_fnc(req: JobRequest):
    """Accept job requests for booking agent"""
    logging.info(f"Accepting booking job {req.job.id}")
    await req.accept(identity="newport-rentals")


def prewarm(proc: agents.JobProcess):
    """Preload models and clients"""
    logging.info("Prewarming Booking Agent...")
    # Models are loaded as needed in entrypoint to avoid memory issues
    logging.info("Booking Agent prewarm complete.")


if __name__ == "__main__":
    logging.info("Starting Newport Beach Booking Agent...")
    
    agents.cli.run_app(
        WorkerOptions(
            request_fnc=request_fnc,
            entrypoint_fnc=entrypoint, 
            prewarm_fnc=prewarm
        )
    )