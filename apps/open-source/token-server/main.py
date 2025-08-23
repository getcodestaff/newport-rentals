import os
import uuid
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from livekit import api
from livekit.api import LiveKitAPI
from livekit.protocol.sip import CreateSIPParticipantRequest
from dotenv import load_dotenv

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
        
        # Create SIP participant using correct LiveKit API
        participant_identity = f"newport_caller_{uuid.uuid4().hex[:8]}"
        
        sip_request = CreateSIPParticipantRequest(
            sip_trunk_id=SIP_TRUNK_ID,
            sip_call_to=request.phone_number,
            room_name=room_name,
            participant_identity=participant_identity,
            participant_name=request.caller_name,
            wait_until_answered=True
        )
        
        print(f"Making call to {request.phone_number} using trunk {SIP_TRUNK_ID} in room {room_name}")
        sip_info = await lk_api.sip.create_sip_participant(sip_request)
        print(f"Call initiated successfully: {sip_info}")
        
        return {
            "success": True,
            "room_name": room_name,
            "call_id": sip_info.participant_identity,
            "phone_number": request.phone_number,
            "message": f"Calling {request.phone_number}..."
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

if __name__ == "__main__":
    # Use 0.0.0.0 to bind to all interfaces for Render deployment
    port = int(os.getenv("PORT", 8002))
    print(f"PORT environment variable: {os.getenv('PORT', 'NOT SET')}")
    print(f"Starting server on 0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
