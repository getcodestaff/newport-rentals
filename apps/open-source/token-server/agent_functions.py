import httpx
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict

# Base URL for your API (will be localhost in development, your domain in production)
BASE_URL = "http://localhost:8002"  # Change to your Render URL in production

async def check_calendar_availability(date: str, duration: int = 60) -> Dict:
    """
    Check available appointment slots for a given date
    
    Args:
        date: Date in YYYY-MM-DD format (e.g., "2024-08-26")
        duration: Appointment duration in minutes (default 60)
    
    Returns:
        Dict with available time slots
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/api/calendar/availability",
                params={"date": date, "duration": duration},
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    slots = data.get("available_slots", [])
                    if slots:
                        # Format for agent to speak naturally
                        slot_descriptions = []
                        for slot in slots[:5]:  # Limit to 5 options
                            slot_descriptions.append(slot["display"])
                        
                        return {
                            "success": True,
                            "message": f"I found {len(slot_descriptions)} available times on {date}:",
                            "available_times": slot_descriptions,
                            "slots_data": slots[:5]  # Keep data for booking
                        }
                    else:
                        return {
                            "success": False,
                            "message": f"I don't have any available appointment slots on {date}. Would you like to try another date?"
                        }
                else:
                    return {"success": False, "message": "Unable to check calendar availability right now."}
            else:
                return {"success": False, "message": "Calendar system is temporarily unavailable."}
                
    except Exception as e:
        logging.error(f"Error checking calendar availability: {e}")
        return {"success": False, "message": "I'm having trouble accessing the calendar right now."}

async def book_calendar_appointment(
    guest_name: str,
    guest_phone: str, 
    start_time: str,
    end_time: str,
    guest_email: str = "",
    description: str = ""
) -> Dict:
    """
    Book an appointment in the calendar
    
    Args:
        guest_name: Guest's full name
        guest_phone: Guest's phone number
        start_time: Appointment start time in ISO format
        end_time: Appointment end time in ISO format
        guest_email: Optional email address
        description: Optional appointment description
    
    Returns:
        Dict with booking confirmation
    """
    try:
        booking_data = {
            "guest_name": guest_name,
            "guest_phone": guest_phone,
            "guest_email": guest_email,
            "start_time": start_time,
            "end_time": end_time,
            "title": f"Newport Beach Rental - {guest_name}",
            "description": description or "Property viewing appointment scheduled via phone"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/api/calendar/book",
                json=booking_data,
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    event_details = data.get("event_details", {})
                    start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    
                    return {
                        "success": True,
                        "message": f"Perfect! I've booked your appointment for {start_dt.strftime('%A, %B %d at %I:%M %p')}. You'll receive a confirmation if you provided an email.",
                        "confirmation_details": {
                            "name": guest_name,
                            "phone": guest_phone,
                            "datetime": start_dt.strftime('%A, %B %d at %I:%M %p'),
                            "event_id": event_details.get("event_id")
                        }
                    }
                else:
                    return {"success": False, "message": "I wasn't able to book that appointment. The time slot might no longer be available."}
            else:
                return {"success": False, "message": "I'm having trouble booking the appointment right now."}
                
    except Exception as e:
        logging.error(f"Error booking calendar appointment: {e}")
        return {"success": False, "message": "I encountered an error while booking your appointment."}

def get_available_dates() -> List[str]:
    """Get next 7 days as available booking dates"""
    today = datetime.now()
    available_dates = []
    
    for i in range(1, 8):  # Next 7 days (skip today)
        date = today + timedelta(days=i)
        # Skip weekends for business appointments
        if date.weekday() < 5:  # Monday = 0, Friday = 4
            available_dates.append({
                "date": date.strftime("%Y-%m-%d"),
                "display": date.strftime("%A, %B %d")
            })
    
    return available_dates

# Agent function schemas for LiveKit (these would be registered with your agent)
AGENT_FUNCTIONS = {
    "check_calendar_availability": {
        "description": "Check available appointment times for property viewings",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format"
                },
                "duration": {
                    "type": "integer", 
                    "description": "Appointment duration in minutes",
                    "default": 60
                }
            },
            "required": ["date"]
        }
    },
    "book_calendar_appointment": {
        "description": "Book a property viewing appointment",
        "parameters": {
            "type": "object",
            "properties": {
                "guest_name": {"type": "string", "description": "Guest's full name"},
                "guest_phone": {"type": "string", "description": "Guest's phone number"},
                "start_time": {"type": "string", "description": "ISO format start time"},
                "end_time": {"type": "string", "description": "ISO format end time"},
                "guest_email": {"type": "string", "description": "Optional email address"},
                "description": {"type": "string", "description": "Appointment notes"}
            },
            "required": ["guest_name", "guest_phone", "start_time", "end_time"]
        }
    }
}