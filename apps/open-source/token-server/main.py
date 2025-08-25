import os
import uuid
import uvicorn
import asyncio
import logging
import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from livekit import api
from livekit.api import LiveKitAPI
from livekit.protocol.sip import CreateSIPParticipantRequest
from dotenv import load_dotenv
from supabase_client import get_supabase_client
from calendar_service import get_calendar_service
from agent_functions import check_calendar_availability, book_calendar_appointment, get_available_dates

# Load environment variables from the .env file in the current directory
load_dotenv()

LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")
LIVEKIT_URL = os.getenv("LIVEKIT_URL")
SIP_TRUNK_ID = os.getenv("SIP_TRUNK_ID")  # Will be set after trunk creation

app = FastAPI()

# Configure CORS to allow requests from our frontend (running on localhost:3000 or 3001)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "https://www.voicesellai.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TokenRequest(BaseModel):
    business_id: str
    room_name: str

class MakeCallRequest(BaseModel):
    phone_number: str
    caller_name: str = "Newport Rentals"

# Database Models
class ProspectCreate(BaseModel):
    business_id: str
    name: Optional[str] = None
    phone_number: str
    email: Optional[str] = None
    notes: Optional[str] = None
    status: str = "new"

class LeadCreate(BaseModel):
    business_id: str
    visitor_name: Optional[str] = None
    visitor_email: Optional[str] = None
    visitor_phone: Optional[str] = None
    inquiry: str

class CreateTrunkRequest(BaseModel):
    sip_address: str  # e.g., "sip.twilio.com"
    username: str
    password: str
    phone_numbers: list[str] = ["*"]  # Allow calls from any number

@app.post("/api/token")
async def get_token(request: TokenRequest):
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
        raise HTTPException(status_code=500, detail="LiveKit server credentials not configured in .env file.")
    
    room_name = request.room_name
    # For the open-source version, the participant identity is simple
    participant_identity = f"visitor-{uuid.uuid4()}"

    token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET) \
        .with_identity(participant_identity) \
        .with_name("Website Visitor") \
        .with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )).to_jwt()

    return {"token": token}

@app.post("/api/make-call")
async def make_call(request: MakeCallRequest):
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET or not LIVEKIT_URL:
        raise HTTPException(status_code=500, detail="LiveKit credentials not configured")
    
    # Format phone number properly - add +1 if missing
    phone_number = request.phone_number.strip()
    if not phone_number.startswith('+'):
        if phone_number.startswith('1'):
            phone_number = '+' + phone_number
        else:
            phone_number = '+1' + phone_number
    
    # Create unique room for this outbound call
    room_name = f"newport_outbound_{uuid.uuid4().hex[:8]}"
    
    try:
        # Validate SIP trunk is configured
        if not SIP_TRUNK_ID:
            raise HTTPException(status_code=500, detail="SIP_TRUNK_ID not configured. Please set up outbound SIP trunk first.")
        
        # Initialize LiveKit API client
        lk_api = LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        
        # Create the room first
        try:
            await lk_api.room.create_room(api.CreateRoomRequest(name=room_name))
        except Exception as room_error:
            print(f"Room creation error: {room_error}")
            # Room might already exist, continue
        
        # Create agent dispatch to ensure newport-rentals agent handles the call
        dispatch_request = api.CreateAgentDispatchRequest(
            agent_name="newport-rentals",
            room=room_name,
            metadata=f'{{"phone_number": "{phone_number}", "caller_name": "{request.caller_name}"}}'
        )
        
        print(f"Creating agent dispatch for newport-rentals in room {room_name}")
        dispatch_info = await lk_api.agent_dispatch.create_dispatch(dispatch_request)
        print(f"Agent dispatch created: {dispatch_info}")
        
        # Then create SIP participant
        participant_identity = f"newport_caller_{uuid.uuid4().hex[:8]}"
        
        sip_request = CreateSIPParticipantRequest(
            sip_trunk_id=SIP_TRUNK_ID,
            sip_call_to=phone_number,
            room_name=room_name,
            participant_identity=participant_identity,
            participant_name=request.caller_name,
            wait_until_answered=True
        )
        
        print(f"Making call to {phone_number} using trunk {SIP_TRUNK_ID} in room {room_name}")
        sip_info = await lk_api.sip.create_sip_participant(sip_request)
        print(f"Call initiated successfully: {sip_info}")
        
        # Log the call to database using Supabase
        try:
            supabase = get_supabase_client()
            if supabase:
                # Check if this phone number is a known prospect
                prospect_result = supabase.table('prospects').select('*').eq('phone_number', phone_number).eq('business_id', 'newport-beach').execute()
                prospect = prospect_result.data[0] if prospect_result.data else None
                
                prospect_id = prospect['id'] if prospect else None
                
                # Create call log
                call_log_data = {
                    "prospect_id": prospect_id,
                    "business_id": "newport-beach",
                    "phone_number": phone_number,
                    "room_name": room_name,
                    "call_status": "initiated"
                }
                
                log_result = supabase.table('call_logs').insert(call_log_data).execute()
                
                # Update prospect call count and last called time if it exists
                if prospect:
                    current_count = prospect.get('call_count', 0)
                    update_data = {
                        "last_called": datetime.utcnow().isoformat(),
                        "call_count": current_count + 1,
                        "status": "contacted"
                    }
                    supabase.table('prospects').update(update_data).eq('id', prospect['id']).execute()
                
                logging.info(f"Call logged successfully")
            
        except Exception as log_error:
            logging.error(f"Failed to log call: {log_error}")
            # Don't fail the call if logging fails
        
        return {
            "success": True,
            "room_name": room_name,
            "call_id": sip_info.participant_identity,
            "phone_number": phone_number,
            "message": f"Calling {phone_number}...",
            "prospect_id": prospect_id if prospect else None
        }
        
    except Exception as e:
        print(f"Call failed with error: {str(e)}")
        print(f"Error type: {type(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to initiate call: {str(e)}")

@app.post("/api/create-trunk") 
async def create_sip_trunk(request: CreateTrunkRequest):
    """Create outbound SIP trunk named 'newport-trunk' for Twilio"""
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET or not LIVEKIT_URL:
        raise HTTPException(status_code=500, detail="LiveKit credentials not configured")
    
    try:
        lk_api = LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        
        # Create the SIP outbound trunk
        trunk_request = api.CreateSipOutboundTrunkRequest(
            name="newport-trunk",
            metadata="Outbound SIP trunk for Newport Beach Vacation Properties",
            address=request.sip_address,
            username=request.username,
            password=request.password,
            phone_numbers=request.phone_numbers
        )
        
        trunk_info = await lk_api.sip.create_sip_outbound_trunk(trunk_request)
        
        return {
            "success": True,
            "trunk_id": trunk_info.sip_trunk_id,
            "name": trunk_info.name,
            "message": f"SIP trunk 'newport-trunk' created successfully! Add SIP_TRUNK_ID={trunk_info.sip_trunk_id} to your .env file"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create SIP trunk: {str(e)}")

# Newport Beach Lead Management Endpoints
@app.post("/api/newport-beach/leads")
async def create_newport_lead(
    lead_data: dict
):
    """Create a new lead for Newport Beach Rentals - Public endpoint for dialer"""
    try:
        supabase = get_supabase_client()
        if not supabase:
            raise HTTPException(status_code=500, detail="Database connection not available")
            
        # Prepare lead data
        lead_data_clean = {
            "business_id": "newport-beach",
            "visitor_name": lead_data.get("visitor_name"),
            "visitor_email": lead_data.get("visitor_email"),
            "visitor_phone": lead_data.get("visitor_phone"),
            "inquiry": lead_data.get("inquiry", "Lead from Newport Beach dialer"),
            "status": "new"
        }
        
        logging.info(f"Creating Newport Beach lead: {lead_data_clean}")
        
        # Insert into database
        result = supabase.table('leads').insert(lead_data_clean).execute()
        
        if result.data:
            logging.info(f"Successfully created lead")
            return {"success": True, "lead": result.data[0]}
        else:
            raise HTTPException(status_code=500, detail="Could not create lead")
        
    except Exception as e:
        logging.error(f"Error creating Newport Beach lead: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create lead: {str(e)}")

@app.get("/api/newport-beach/leads")
async def get_newport_leads(
    limit: int = 50,
    offset: int = 0
):
    """Get all leads for Newport Beach Rentals"""
    try:
        supabase = get_supabase_client()
        if not supabase:
            raise HTTPException(status_code=500, detail="Database connection not available")
            
        result = supabase.table('leads').select('*').eq('business_id', 'newport-beach').range(offset, offset + limit - 1).order('captured_at', desc=True).execute()
        
        return {
            "success": True,
            "leads": result.data,
            "count": len(result.data),
            "business_id": "newport-beach"
        }
        
    except Exception as e:
        logging.error(f"Error fetching Newport Beach leads: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch leads: {str(e)}")

@app.get("/api/newport-beach/leads/{lead_id}")
async def get_newport_lead(
    lead_id: int,
):
    """Get specific lead by ID"""
    try:
        supabase = get_supabase_client()
        if not supabase:
            raise HTTPException(status_code=500, detail="Database connection not available")
            
        result = supabase.table('leads').select('*').eq('id', lead_id).eq('business_id', 'newport-beach').execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        return {"success": True, "lead": result.data[0]}
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error fetching lead {lead_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch lead: {str(e)}")

@app.put("/api/newport-beach/leads/{lead_id}")
async def update_newport_lead(
    lead_id: int,
    update_data: dict,
):
    """Update lead status or information"""
    try:
        supabase = get_supabase_client()
        if not supabase:
            raise HTTPException(status_code=500, detail="Database connection not available")
            
        # Check if lead exists
        existing_result = supabase.table('leads').select('*').eq('id', lead_id).eq('business_id', 'newport-beach').execute()
        
        if not existing_result.data:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        # Update the lead
        result = supabase.table('leads').update(update_data).eq('id', lead_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to update lead")
        
        return {"success": True, "lead": result.data[0]}
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error updating lead {lead_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update lead: {str(e)}")

# Newport Beach Dialer Endpoints
@app.post("/api/newport-beach/prospects")
async def create_prospect(
    prospect_data: dict,
):
    """Add a new prospect to call list"""
    try:
        supabase = get_supabase_client()
        if not supabase:
            raise HTTPException(status_code=500, detail="Database connection not available")
            
        prospect_create_data = {
            "business_id": "newport-beach",
            "name": prospect_data.get("name"),
            "phone_number": prospect_data.get("phone_number"),
            "email": prospect_data.get("email"),
            "notes": prospect_data.get("notes"),
            "status": "new"
        }
        
        logging.info(f"Creating prospect: {prospect_create_data}")
        
        result = supabase.table('prospects').insert(prospect_create_data).execute()
        
        if result.data:
            return {"success": True, "prospect": result.data[0]}
        else:
            raise HTTPException(status_code=500, detail="Failed to create prospect")
        
    except Exception as e:
        logging.error(f"Error creating prospect: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create prospect: {str(e)}")

@app.get("/api/newport-beach/prospects")
async def get_prospects(
    limit: int = 50,
    offset: int = 0,
    status: str = None,
):
    """Get prospects for the dialer"""
    try:
        supabase = get_supabase_client()
        if not supabase:
            raise HTTPException(status_code=500, detail="Database connection not available")
            
        query = supabase.table('prospects').select('*').eq('business_id', 'newport-beach')
        
        if status:
            query = query.eq('status', status)
            
        result = query.range(offset, offset + limit - 1).order('created_at', desc=True).execute()
        
        return {
            "success": True,
            "prospects": result.data,
            "count": len(result.data),
            "business_id": "newport-beach"
        }
        
    except Exception as e:
        logging.error(f"Error fetching prospects: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch prospects: {str(e)}")

@app.put("/api/newport-beach/prospects/{prospect_id}")
async def update_prospect(
    prospect_id: int,
    update_data: dict,
):
    """Update prospect status or information"""
    try:
        supabase = get_supabase_client()
        if not supabase:
            raise HTTPException(status_code=500, detail="Database connection not available")
            
        # Update prospect
        result = supabase.table('prospects').update(update_data).eq('id', prospect_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Prospect not found")
        
        return {"success": True, "prospect": result.data[0]}
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error updating prospect {prospect_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update prospect: {str(e)}")

@app.get("/api/newport-beach/call-logs")
async def get_call_logs(
    limit: int = 50,
    offset: int = 0,
):
    """Get call history for Newport Beach"""
    try:
        supabase = get_supabase_client()
        if not supabase:
            raise HTTPException(status_code=500, detail="Database connection not available")
            
        result = supabase.table('call_logs').select('*').eq('business_id', 'newport-beach').range(offset, offset + limit - 1).order('created_at', desc=True).execute()
        
        return {
            "success": True,
            "calls": result.data,
            "count": len(result.data),
            "business_id": "newport-beach"
        }
        
    except Exception as e:
        logging.error(f"Error fetching call logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch call logs: {str(e)}")

@app.get("/api/test-db")
async def test_database_connection():
    """Simple test to check if database is working"""
    try:
        supabase = get_supabase_client()
        if not supabase:
            return {
                "success": False,
                "database_connected": False,
                "error": "Supabase client not initialized",
                "message": "Database connection failed"
            }
        
        # Test database connection by querying prospects
        result = supabase.table('prospects').select('*').limit(1).execute()
        
        return {
            "success": True,
            "database_connected": True,
            "sample_prospect": result.data[0] if result.data else None,
            "total_prospects": len(result.data) if result.data else 0,
            "message": "Supabase connection working!"
        }
        
    except Exception as e:
        return {
            "success": False,
            "database_connected": False,
            "error": str(e),
            "message": "Database connection failed"
        }

@app.get("/api/debug")
async def debug_config():
    """Debug endpoint to check configuration"""
    return {
        "environment_vars": {
            "LIVEKIT_URL": LIVEKIT_URL,
            "LIVEKIT_API_KEY": "***" if LIVEKIT_API_KEY else None,
            "LIVEKIT_API_SECRET": "***" if LIVEKIT_API_SECRET else None,
            "SIP_TRUNK_ID": SIP_TRUNK_ID
        },
        "expected_trunk": "ST_eWihSQEyGTF5",
        "room_prefix": "newport_outbound_"
    }

@app.get("/api/status")
async def get_status():
    """Get configuration status and API information"""
    
    # Check environment variables
    env_status = {
        "livekit_api_key": "✅ Set" if LIVEKIT_API_KEY else "❌ Missing",
        "livekit_api_secret": "✅ Set" if LIVEKIT_API_SECRET else "❌ Missing", 
        "livekit_url": "✅ Set" if LIVEKIT_URL else "❌ Missing",
        "sip_trunk_id": "✅ Set" if SIP_TRUNK_ID else "❌ Missing - Required for outbound calls"
    }
    
    # API endpoints info
    endpoints = {
        "POST /api/token": {
            "description": "Generate LiveKit access token for web sessions",
            "required_fields": ["business_id", "room_name"],
            "status": "✅ Active"
        },
        "POST /api/make-call": {
            "description": "Initiate outbound SIP call through Newport agent",
            "required_fields": ["phone_number", "caller_name (optional)"],
            "status": "✅ Active" if all([LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL, SIP_TRUNK_ID]) else "⚠️ Missing Config"
        }
    }
    
    # Configuration requirements
    livekit_config = {
        "sip_trunk_setup": "❌ Create outbound SIP trunk named 'newport-trunk' in LiveKit Cloud",
        "sip_trunk_id": "❌ Set SIP_TRUNK_ID environment variable after trunk creation",
        "dispatch_rules": "📋 Upload outbound-dispatch-rule.json to LiveKit Cloud",
        "agent_deployment": "🚀 Ensure 'newport-rentals' agent is deployed"
    }
    
    return {
        "service": "Newport Rentals API Server",
        "status": "running",
        "environment": env_status,
        "endpoints": endpoints,
        "livekit_configuration": livekit_config,
        "frontend_integration": {
            "cors_enabled": "https://www.voicesellai.com",
            "dialer_endpoint": "POST /api/make-call"
        }
    }

@app.get("/dashboard", response_class=HTMLResponse)
async def call_dashboard():
    """Live Call Dashboard"""
    try:
        with open("dashboard.html", "r") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Dashboard not found</h1>", status_code=404)

@app.get("/dialer", response_class=HTMLResponse)
async def newport_dialer():
    """Newport Beach Dialer Interface"""
    try:
        with open("dialer.html", "r") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Dialer not found</h1>", status_code=404)

@app.get("/", response_class=HTMLResponse)
async def api_dashboard():
    """API Management Dashboard"""
    
    # Get status info
    status_info = await get_status()
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Newport Rentals API Dashboard</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background-color: #f5f5f5; }}
            .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
            h2 {{ color: #34495e; margin-top: 30px; }}
            .status-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0; }}
            .status-card {{ background: #f8f9fa; padding: 20px; border-radius: 8px; border-left: 4px solid #3498db; }}
            .endpoint-card {{ background: #e8f5e8; padding: 15px; border-radius: 8px; margin: 10px 0; }}
            .config-card {{ background: #fff3cd; padding: 15px; border-radius: 8px; margin: 10px 0; }}
            .code-block {{ background: #2d3748; color: #e2e8f0; padding: 15px; border-radius: 6px; font-family: monospace; margin: 10px 0; overflow-x: auto; }}
            .success {{ color: #28a745; }}
            .warning {{ color: #ffc107; }}
            .error {{ color: #dc3545; }}
            ul {{ list-style-type: none; padding: 0; }}
            li {{ margin: 8px 0; padding: 8px; background: rgba(52, 152, 219, 0.1); border-radius: 4px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🏖️ Newport Rentals API Dashboard</h1>
            <p><strong>Service Status:</strong> <span class="success">Running ✅</span></p>
            
            <div class="status-grid">
                <div class="status-card">
                    <h3>Environment Configuration</h3>
                    <ul>
                        <li>LiveKit API Key: {status_info['environment']['livekit_api_key']}</li>
                        <li>LiveKit API Secret: {status_info['environment']['livekit_api_secret']}</li>
                        <li>LiveKit URL: {status_info['environment']['livekit_url']}</li>
                    </ul>
                </div>
                
                <div class="status-card">
                    <h3>Frontend Integration</h3>
                    <ul>
                        <li>CORS Enabled: ✅ https://www.voicesellai.com</li>
                        <li>Dialer Integration: ✅ Ready</li>
                        <li>Token Generation: ✅ Active</li>
                    </ul>
                </div>
            </div>

            <h2>📡 API Endpoints</h2>
            
            <div class="endpoint-card">
                <h3>POST /api/make-call</h3>
                <p><strong>Purpose:</strong> Initiate outbound calls through Newport agent</p>
                <p><strong>Status:</strong> {status_info['endpoints']['POST /api/make-call']['status']}</p>
                <p><strong>Example Request:</strong></p>
                <div class="code-block">
POST /api/make-call
Content-Type: application/json

{{
    "phone_number": "+1234567890",
    "caller_name": "Newport Rentals"
}}
                </div>
            </div>

            <div class="endpoint-card">
                <h3>POST /api/token</h3>
                <p><strong>Purpose:</strong> Generate LiveKit tokens for web sessions</p>
                <p><strong>Status:</strong> {status_info['endpoints']['POST /api/token']['status']}</p>
                <p><strong>Example Request:</strong></p>
                <div class="code-block">
POST /api/token
Content-Type: application/json

{{
    "business_id": "newport-rentals",
    "room_name": "web_session_123"
}}
                </div>
            </div>

            <h2>⚙️ LiveKit Cloud Configuration Required</h2>
            
            <div class="config-card">
                <h3>🔧 Manual Setup Steps</h3>
                <ol>
                    <li><strong>Configure SIP Trunk:</strong> Set up outbound SIP provider in LiveKit Cloud dashboard</li>
                    <li><strong>Upload Dispatch Rules:</strong> Import <code>outbound-dispatch-rule.json</code></li>
                    <li><strong>Deploy Agent:</strong> Ensure 'newport-rentals' agent is running</li>
                    <li><strong>Update SIP Trunk ID:</strong> Replace empty string on line 76 in token-server code</li>
                </ol>
            </div>

            <h2>📊 Current Deployment Status</h2>
            <div class="status-grid">
                <div class="config-card">
                    <h4>Agent Configuration</h4>
                    <ul>
                        <li>Agent Name: newport-rentals</li>
                        <li>Personality: Regina (Newport Beach Concierge)</li>
                        <li>Room Prefixes: newport_, newport_outbound_</li>
                        <li>Greeting: Vacation rental confirmation script</li>
                    </ul>
                </div>
                
                <div class="config-card">
                    <h4>Room & Call Flow</h4>
                    <ul>
                        <li>Inbound: newport_ → Regina greeting</li>
                        <li>Outbound: newport_outbound_ → Regina script</li>
                        <li>Web Sessions: Custom room names</li>
                        <li>Call Duration: 60s timeout for user away</li>
                    </ul>
                </div>
            </div>

            <h2>🎯 Integration Examples</h2>
            
            <h3>Dialer Frontend Integration</h3>
            <div class="code-block">
// Frontend JavaScript example
async function makeCall(phoneNumber) {{
    const response = await fetch('/api/make-call', {{
        method: 'POST',
        headers: {{
            'Content-Type': 'application/json',
        }},
        body: JSON.stringify({{
            phone_number: phoneNumber,
            caller_name: 'Newport Rentals'
        }})
    }});
    
    const result = await response.json();
    console.log('Call initiated:', result);
}}
            </div>

            <p><em>Last updated: {status_info['service']} API Server</em></p>
        </div>
    </body>
    </html>
    """
    
    return html_content

@app.get("/api/calls/live")
async def get_live_calls():
    """Get all currently active calls from LiveKit"""
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET or not LIVEKIT_URL:
        raise HTTPException(status_code=500, detail="LiveKit credentials not configured")
    
    try:
        lk_api = LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        
        # Get all rooms
        rooms_response = await lk_api.room.list_rooms()
        active_calls = []
        
        for room in rooms_response.rooms:
            # Filter for outbound call rooms
            if room.name.startswith("newport_outbound_"):
                # Get participants in this room
                participants_response = await lk_api.room.list_participants(room.name)
                
                call_data = {
                    "room_name": room.name,
                    "creation_time": room.creation_time,
                    "num_participants": room.num_participants,
                    "participants": [],
                    "call_status": "active" if room.num_participants > 0 else "ended",
                    "call_type": "outbound"
                }
                
                # Add participant details
                for participant in participants_response.participants:
                    participant_data = {
                        "identity": participant.identity,
                        "name": participant.name,
                        "joined_at": participant.joined_at,
                        "is_agent": participant.identity.startswith("newport-rentals"),
                        "is_sip": participant.identity.startswith("newport_caller_")
                    }
                    call_data["participants"].append(participant_data)
                
                active_calls.append(call_data)
        
        return {
            "success": True,
            "active_calls": active_calls,
            "total_calls": len(active_calls),
            "timestamp": datetime.datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get live calls: {str(e)}")

@app.get("/api/calls/history")
async def get_call_history():
    """Get recent call history from LiveKit"""
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET or not LIVEKIT_URL:
        raise HTTPException(status_code=500, detail="LiveKit credentials not configured")
    
    try:
        lk_api = LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        
        # Get all rooms (including ended ones)
        rooms_response = await lk_api.room.list_rooms()
        call_history = []
        
        for room in rooms_response.rooms:
            if room.name.startswith("newport_outbound_"):
                # Calculate call duration
                creation_time = datetime.datetime.fromtimestamp(room.creation_time)
                duration = None
                if room.num_participants == 0:  # Call ended
                    # Estimate duration (you might want to store actual end times)
                    duration = "completed"
                
                call_data = {
                    "room_name": room.name,
                    "creation_time": room.creation_time,
                    "start_time": creation_time.isoformat(),
                    "num_participants": room.num_participants,
                    "call_status": "active" if room.num_participants > 0 else "ended",
                    "duration": duration,
                    "call_type": "outbound"
                }
                
                call_history.append(call_data)
        
        # Sort by creation time (newest first)
        call_history.sort(key=lambda x: x["creation_time"], reverse=True)
        
        return {
            "success": True,
            "call_history": call_history[:50],  # Last 50 calls
            "total_calls": len(call_history),
            "timestamp": datetime.datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get call history: {str(e)}")

@app.get("/api/calls/stats")
async def get_call_stats():
    """Get call statistics and metrics"""
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET or not LIVEKIT_URL:
        raise HTTPException(status_code=500, detail="LiveKit credentials not configured")
    
    try:
        lk_api = LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        
        # Get all rooms
        rooms_response = await lk_api.room.list_rooms()
        
        total_calls = 0
        active_calls = 0
        ended_calls = 0
        
        for room in rooms_response.rooms:
            if room.name.startswith("newport_outbound_"):
                total_calls += 1
                if room.num_participants > 0:
                    active_calls += 1
                else:
                    ended_calls += 1
        
        # Calculate success rate (calls with participants)
        success_rate = (ended_calls / total_calls * 100) if total_calls > 0 else 0
        
        return {
            "success": True,
            "stats": {
                "total_calls": total_calls,
                "active_calls": active_calls,
                "ended_calls": ended_calls,
                "success_rate": round(success_rate, 2),
                "agent_status": "online" if active_calls > 0 else "idle"
            },
            "timestamp": datetime.datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get call stats: {str(e)}")

# Calendar Integration Endpoints
@app.get("/api/calendar/availability")
async def check_calendar_availability(
    date: str,  # Format: 2024-08-26
    duration: int = 60  # Duration in minutes
):
    """Check available time slots for a specific date"""
    try:
        calendar_service = get_calendar_service()
        
        # Parse the date and create start/end times for the day
        from datetime import datetime, timedelta
        start_date = datetime.fromisoformat(date)
        end_date = start_date + timedelta(days=1)
        
        # Convert to ISO format
        start_iso = start_date.isoformat()
        end_iso = end_date.isoformat()
        
        available_slots = calendar_service.check_availability(start_iso, end_iso, duration)
        
        return {
            "success": True,
            "date": date,
            "available_slots": available_slots,
            "total_slots": len(available_slots)
        }
        
    except Exception as e:
        logging.error(f"Error checking calendar availability: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to check availability: {str(e)}")

@app.post("/api/calendar/book")
async def book_appointment(booking_data: dict):
    """Book an appointment in the calendar"""
    try:
        calendar_service = get_calendar_service()
        
        # Extract booking data
        start_time = booking_data.get('start_time')
        end_time = booking_data.get('end_time')
        guest_name = booking_data.get('guest_name', '')
        guest_phone = booking_data.get('guest_phone', '')
        guest_email = booking_data.get('guest_email', '')
        title = booking_data.get('title', f'Newport Beach Rental - {guest_name}')
        description = booking_data.get('description', 'Property viewing appointment')
        
        if not start_time or not end_time:
            raise HTTPException(status_code=400, detail="start_time and end_time are required")
        
        # Create the calendar event
        result = calendar_service.create_event(
            title=title,
            start_time=start_time,
            end_time=end_time,
            guest_name=guest_name,
            guest_phone=guest_phone,
            guest_email=guest_email,
            description=description
        )
        
        if result.get('success'):
            # Also log this booking in our database
            try:
                supabase = get_supabase_client()
                if supabase:
                    booking_log = {
                        "business_id": "newport-beach",
                        "visitor_name": guest_name,
                        "visitor_phone": guest_phone,
                        "visitor_email": guest_email,
                        "inquiry": f"Calendar booking: {title}",
                        "status": "scheduled"
                    }
                    supabase.table('leads').insert(booking_log).execute()
                    logging.info("Booking logged to database")
            except Exception as log_error:
                logging.error(f"Failed to log booking to database: {log_error}")
            
            return {
                "success": True,
                "message": f"Appointment booked for {guest_name}",
                "event_details": result
            }
        else:
            raise HTTPException(status_code=500, detail=result.get('error', 'Failed to create booking'))
        
    except Exception as e:
        logging.error(f"Error booking appointment: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to book appointment: {str(e)}")

@app.get("/api/calendar/events")
async def get_upcoming_events(days: int = 7):
    """Get upcoming calendar events"""
    try:
        calendar_service = get_calendar_service()
        events = calendar_service.get_upcoming_events(days)
        
        return {
            "success": True,
            "upcoming_events": events,
            "total_events": len(events),
            "days_ahead": days
        }
        
    except Exception as e:
        logging.error(f"Error getting calendar events: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get events: {str(e)}")

@app.get("/api/calendar/test")
async def test_calendar_connection():
    """Test Google Calendar connection"""
    try:
        calendar_service = get_calendar_service()
        
        if calendar_service.authenticate():
            # Try to get a few upcoming events as a test
            events = calendar_service.get_upcoming_events(1)
            return {
                "success": True,
                "message": "✅ Google Calendar connected successfully",
                "calendar_id": calendar_service.calendar_id,
                "test_events_found": len(events)
            }
        else:
            return {
                "success": False,
                "message": "❌ Failed to connect to Google Calendar",
                "error": "Authentication failed"
            }
            
    except Exception as e:
        return {
            "success": False,
            "message": "❌ Calendar connection error",
            "error": str(e)
        }

# Agent Function Endpoints (for LiveKit agent to call during conversations)
@app.post("/api/agent/check-availability")
async def agent_check_availability(request_data: dict):
    """Agent function to check calendar availability during conversation"""
    try:
        date = request_data.get("date")
        duration = request_data.get("duration", 60)
        
        if not date:
            return {"success": False, "message": "Please provide a date to check availability."}
        
        result = await check_calendar_availability(date, duration)
        return result
        
    except Exception as e:
        logging.error(f"Agent availability check error: {e}")
        return {"success": False, "message": "I'm having trouble checking the calendar right now."}

@app.post("/api/agent/book-appointment") 
async def agent_book_appointment(request_data: dict):
    """Agent function to book appointments during conversation"""
    try:
        guest_name = request_data.get("guest_name")
        guest_phone = request_data.get("guest_phone") 
        start_time = request_data.get("start_time")
        end_time = request_data.get("end_time")
        guest_email = request_data.get("guest_email", "")
        description = request_data.get("description", "")
        
        if not all([guest_name, guest_phone, start_time, end_time]):
            return {"success": False, "message": "I need your name, phone number, and preferred time to book the appointment."}
        
        result = await book_calendar_appointment(
            guest_name=guest_name,
            guest_phone=guest_phone,
            start_time=start_time,
            end_time=end_time,
            guest_email=guest_email,
            description=description
        )
        return result
        
    except Exception as e:
        logging.error(f"Agent booking error: {e}")
        return {"success": False, "message": "I encountered an error while booking your appointment."}

@app.get("/api/agent/available-dates")
async def agent_available_dates():
    """Get upcoming available dates for agent to suggest"""
    try:
        dates = get_available_dates()
        return {
            "success": True,
            "available_dates": dates,
            "message": "Here are the upcoming dates available for property viewings:"
        }
    except Exception as e:
        logging.error(f"Error getting available dates: {e}")
        return {"success": False, "message": "I'm having trouble getting available dates."}

# WebSocket endpoint for real-time call data broadcasting
@app.websocket("/ws/calls")
async def websocket_calls(websocket: WebSocket):
    """WebSocket endpoint for real-time call data broadcasting"""
    await websocket.accept()
    
    try:
        while True:
            # Send live call data every 5 seconds
            lk_api = LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            rooms_response = await lk_api.room.list_rooms()
            
            active_calls = []
            for room in rooms_response.rooms:
                if room.name.startswith("newport_outbound_"):
                    call_data = {
                        "room_name": room.name,
                        "num_participants": room.num_participants,
                        "call_status": "active" if room.num_participants > 0 else "ended",
                        "timestamp": datetime.datetime.now().isoformat()
                    }
                    active_calls.append(call_data)
            
            await websocket.send_json({
                "type": "call_update",
                "data": {
                    "active_calls": active_calls,
                    "total_active": len([c for c in active_calls if c["call_status"] == "active"])
                }
            })
            
            await asyncio.sleep(5)  # Update every 5 seconds
            
    except WebSocketDisconnect:
        print("WebSocket client disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
        await websocket.close()

if __name__ == "__main__":
    # Use 0.0.0.0 to bind to all interfaces for Render deployment
    port = int(os.getenv("PORT", 8002))
    print(f"PORT environment variable: {os.getenv('PORT', 'NOT SET')}")
    print(f"Starting server on 0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
