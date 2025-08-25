import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import logging

class GoogleCalendarService:
    def __init__(self):
        self.service = None
        self.calendar_id = os.getenv('GOOGLE_CALENDAR_ID', 'primary')
        self.credentials_file = 'google-credentials.json'
        self.scopes = ['https://www.googleapis.com/auth/calendar']
        
    def authenticate(self):
        """Authenticate with Google Calendar API using service account"""
        try:
            # Load service account credentials
            if os.path.exists(self.credentials_file):
                creds = service_account.Credentials.from_service_account_file(
                    self.credentials_file, scopes=self.scopes
                )
            else:
                # Fallback to environment variable
                service_account_info = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
                if service_account_info:
                    creds = service_account.Credentials.from_service_account_info(
                        json.loads(service_account_info), scopes=self.scopes
                    )
                else:
                    raise Exception("Google Calendar credentials not found")
            
            self.service = build('calendar', 'v3', credentials=creds)
            logging.info("✅ Google Calendar service authenticated")
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to authenticate Google Calendar: {e}")
            return False
    
    def check_availability(self, start_date: str, end_date: str, duration_minutes: int = 60) -> List[Dict]:
        """Check available time slots between start and end date"""
        if not self.service:
            if not self.authenticate():
                return []
        
        try:
            # Parse dates
            start_time = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            end_time = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            
            # Get busy times from calendar
            freebusy_query = {
                'timeMin': start_time.isoformat(),
                'timeMax': end_time.isoformat(),
                'timeZone': 'America/Los_Angeles',  # Newport Beach timezone
                'items': [{'id': self.calendar_id}]
            }
            
            freebusy_result = self.service.freebusy().query(body=freebusy_query).execute()
            busy_times = freebusy_result['calendars'][self.calendar_id].get('busy', [])
            
            # Generate available slots
            available_slots = []
            current_time = start_time
            
            # Only show slots during business hours (9 AM - 6 PM)
            while current_time + timedelta(minutes=duration_minutes) <= end_time:
                # Skip non-business hours
                if current_time.hour < 9 or current_time.hour >= 18:
                    current_time += timedelta(minutes=30)
                    continue
                    
                slot_end = current_time + timedelta(minutes=duration_minutes)
                
                # Check if this slot conflicts with busy times
                is_available = True
                for busy in busy_times:
                    busy_start = datetime.fromisoformat(busy['start'].replace('Z', '+00:00'))
                    busy_end = datetime.fromisoformat(busy['end'].replace('Z', '+00:00'))
                    
                    if (current_time < busy_end and slot_end > busy_start):
                        is_available = False
                        break
                
                if is_available:
                    available_slots.append({
                        'start': current_time.isoformat(),
                        'end': slot_end.isoformat(),
                        'display': current_time.strftime('%A, %B %d at %I:%M %p'),
                        'date': current_time.strftime('%Y-%m-%d'),
                        'time': current_time.strftime('%I:%M %p')
                    })
                
                # Move to next 30-minute slot
                current_time += timedelta(minutes=30)
                
                # Limit to 8 available slots to avoid overwhelming
                if len(available_slots) >= 8:
                    break
            
            return available_slots
            
        except HttpError as e:
            logging.error(f"Google Calendar API error: {e}")
            return []
        except Exception as e:
            logging.error(f"Error checking availability: {e}")
            return []
    
    def create_event(self, title: str, start_time: str, end_time: str, 
                    guest_name: str = "", guest_phone: str = "", guest_email: str = "", 
                    description: str = "", location: str = "Newport Beach, CA") -> Dict:
        """Create a calendar event for rental booking"""
        if not self.service:
            if not self.authenticate():
                return {'success': False, 'error': 'Authentication failed'}
        
        try:
            # Build event description
            event_description = f"Newport Beach Rental Inquiry\n\n"
            if guest_name:
                event_description += f"Guest: {guest_name}\n"
            if guest_phone:
                event_description += f"Phone: {guest_phone}\n"
            if guest_email:
                event_description += f"Email: {guest_email}\n"
            if description:
                event_description += f"\nNotes: {description}"
                
            event = {
                'summary': title,
                'location': location,
                'description': event_description,
                'start': {
                    'dateTime': start_time,
                    'timeZone': 'America/Los_Angeles',
                },
                'end': {
                    'dateTime': end_time,
                    'timeZone': 'America/Los_Angeles',
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 24 * 60},  # 1 day before
                        {'method': 'popup', 'minutes': 60},       # 1 hour before
                    ],
                },
            }
            
            # Add guest as attendee if email provided
            if guest_email:
                event['attendees'] = [{'email': guest_email, 'displayName': guest_name}]
            
            created_event = self.service.events().insert(
                calendarId=self.calendar_id, 
                body=event,
                sendUpdates='all' if guest_email else 'none'
            ).execute()
            
            logging.info(f"✅ Calendar event created: {created_event['id']}")
            
            return {
                'success': True,
                'event_id': created_event['id'],
                'event_link': created_event.get('htmlLink'),
                'start_time': created_event['start']['dateTime'],
                'end_time': created_event['end']['dateTime'],
                'summary': created_event['summary']
            }
            
        except HttpError as e:
            logging.error(f"Failed to create calendar event: {e}")
            return {'success': False, 'error': f'Calendar API error: {str(e)}'}
        except Exception as e:
            logging.error(f"Error creating event: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_upcoming_events(self, days_ahead: int = 7) -> List[Dict]:
        """Get upcoming events for the next few days"""
        if not self.service:
            if not self.authenticate():
                return []
        
        try:
            now = datetime.utcnow().isoformat() + 'Z'
            future = (datetime.utcnow() + timedelta(days=days_ahead)).isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=now,
                timeMax=future,
                maxResults=20,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            return [{
                'id': event['id'],
                'summary': event.get('summary', 'No Title'),
                'start': event['start'].get('dateTime', event['start'].get('date')),
                'end': event['end'].get('dateTime', event['end'].get('date')),
                'location': event.get('location', ''),
                'description': event.get('description', '')
            } for event in events]
            
        except HttpError as e:
            logging.error(f"Failed to get upcoming events: {e}")
            return []
        except Exception as e:
            logging.error(f"Error getting events: {e}")
            return []

# Global calendar service instance
calendar_service = GoogleCalendarService()

def get_calendar_service():
    """Get the calendar service instance"""
    return calendar_service