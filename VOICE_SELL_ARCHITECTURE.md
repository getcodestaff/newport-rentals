# Voice Sell AI - System Architecture & Call Flow

## Overview
Voice Sell AI is a real-time voice conversation system that uses LiveKit for WebRTC communication, with AI agents for natural language processing.

## System Components

### 1. Frontend (Next.js)
- **Location**: `apps/open-source/frontend/`
- **Port**: 3000 (development)
- **Purpose**: User interface for voice conversations
- **Key Files**:
  - `app/(app)/page.tsx` - Main page
  - `app/(app)/devin/page.tsx` - Devin's page
  - `components/app.tsx` - Main app component
  - `components/app-devin.tsx` - Devin's app component
  - `hooks/useConnectionDetails.ts` - Connection management
  - `hooks/useConnectionDetailsDevin.ts` - Devin's connection management

### 2. Token Server (FastAPI)
- **Location**: `apps/open-source/token-server/`
- **Port**: 8002
- **Purpose**: Generate secure LiveKit access tokens
- **Key Files**:
  - `main.py` - Token generation server
- **Environment Variables**:
  - `LIVEKIT_API_KEY`
  - `LIVEKIT_API_SECRET`

### 3. Agent (Python)
- **Location**: `apps/open-source/agent/`
- **Purpose**: AI conversation processing
- **Key Files**:
  - `main.py` - Main agent logic
  - `core_agent.py` - Business logic
  - `prompt.template` - AI instructions template
- **Environment Variables**:
  - `LIVEKIT_URL`
  - `LIVEKIT_API_KEY`
  - `LIVEKIT_API_SECRET`
  - `DEEPGRAM_API_KEY`
  - `GROQ_API_KEY`
  - `CARTESIA_API_KEY`
  - `WEBHOOK_URL`

### 4. LiveKit Server (Cloud)
- **Purpose**: Real-time communication hub
- **Protocol**: WebRTC + WebSocket
- **Features**: Room management, media routing, signaling

## Detailed Call Flow

### Phase 1: Frontend Initialization

#### 1.1 User Access
```
User visits: https://voice-sell-demo.onrender.com/
OR
User visits: https://voice-sell-demo.onrender.com/devin
```

#### 1.2 Connection Details Request
```typescript
// Frontend calls token server
const response = await fetch('/api/connection-details');
const data = await response.json();
```

**Token Server Processing**:
```python
# apps/open-source/token-server/main.py
@app.get("/api/connection-details")
async def get_connection_details():
    # Generate unique identifiers
    participant_name = 'user'
    participant_identity = f"voice_assistant_user_{random.randint(0, 9999)}"
    room_name = f"voice_assistant_room_{random.randint(0, 9999)}"
    
    # Create JWT token
    token = AccessToken(API_KEY, API_SECRET)
    token.with_identity(participant_identity)
    token.with_name(participant_name)
    token.with_grants(VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    ))
    
    return {
        "serverUrl": LIVEKIT_URL,
        "roomName": room_name,
        "participantToken": token.to_jwt(),
        "participantName": participant_name,
    }
```

**For Devin Page**:
```python
# apps/open-source/token-server/main.py (devin endpoint)
room_name = f"devin_voice_assistant_room_{random.randint(0, 9999)}"
```

### Phase 2: LiveKit Connection

#### 2.1 Frontend Connection
```typescript
// Frontend establishes WebSocket connection
<LiveKitRoom
  serverUrl={connectionDetails.serverUrl}
  token={connectionDetails.participantToken}
  audio={true}
  onConnected={() => console.log("Connected to LiveKit")}
  onDisconnected={() => console.log("Disconnected from LiveKit")}
>
```

#### 2.2 LiveKit Server Processing
```
LiveKit Server:
1. Validates JWT token
2. Creates/joins room: "voice_assistant_room_XXXX"
3. Establishes WebRTC connection
4. Sets up media streams
5. Waits for agent to join
```

### Phase 3: Agent Connection

#### 3.1 Agent Detection
```python
# apps/open-source/agent/main.py
async def request_fnc(req: JobRequest):
    logging.info(f"Received job request {req.job.id} for room {req.job.room}")
    await req.accept(identity="voice-sell-agent")
```

#### 3.2 Agent Initialization
```python
# apps/open-source/agent/main.py
def prewarm(proc: agents.JobProcess):
    # Load environment variables
    load_dotenv()
    
    # Initialize VAD (Voice Activity Detection)
    proc.userdata["vad"] = silero.VAD.load()
    
    # Initialize TTS (Text-to-Speech)
    proc.userdata["tts_default"] = cartesia.TTS(model="sonic-english")
    
    logging.info("Prewarm complete: VAD model and TTS client initialized.")
```

#### 3.3 Agent Session Setup
```python
# apps/open-source/agent/main.py
async def entrypoint(ctx: agents.JobContext):
    # Connect to LiveKit room
    await ctx.connect()
    
    # Initialize AI components
    stt = deepgram.STT()  # Speech-to-Text
    llm = groq.LLM(model="llama-3.3-70b-versatile")  # Language Model
    vad = ctx.proc.userdata["vad"]  # Voice Activity Detection
    tts = ctx.proc.userdata["tts_default"]  # Text-to-Speech
    
    # Create agent session
    session = agents.AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        vad=vad,
        turn_detection="vad",
        user_away_timeout=60,
    )
    
    # Load instructions based on room name
    room_name = ctx.room.name
    if "devin" in room_name.lower():
        # Ashley's personality instructions
        instructions = "You are Ashley, Devin's personal assistant..."
    else:
        # Default instructions from template
        instructions = prompt_template.substitute(...)
    
    # Create business agent
    agent = BusinessAgent(instructions=instructions)
    
    # Start session
    await session.start(room=ctx.room, agent=agent)
```

### Phase 4: Real-time Conversation

#### 4.1 Audio Processing Pipeline
```
User speaks → Microphone → Browser → LiveKit → Agent
                                    ↓
Agent processes: STT → LLM → TTS → LiveKit → Browser → Speakers
```

#### 4.2 Speech-to-Text (Deepgram)
```python
# Agent receives audio stream
# Deepgram converts speech to text
transcript = await stt.transcribe(audio_chunk)
```

#### 4.3 Language Processing (Groq)
```python
# Groq LLM processes the transcript
response = await llm.generate(
    messages=[{"role": "user", "content": transcript}],
    model="llama-3.3-70b-versatile"
)
```

#### 4.4 Text-to-Speech (Cartesia)
```python
# Cartesia converts response to speech
audio = await tts.synthesize(response.content)
```

#### 4.5 Voice Activity Detection (Silero)
```python
# Silero VAD detects when user is speaking
is_speaking = vad.detect(audio_chunk)
```

### Phase 5: Lead Capture (Optional)

#### 5.1 Form Display
```python
# Agent calls form display function
await session.call_tool("present_verification_form", {
    "name": user_name,
    "email": user_email,
    "inquiry": user_inquiry
})
```

#### 5.2 Form Submission
```typescript
// Frontend handles form submission
const handleFormSubmit = async (room: Room, data: any) => {
    await room.localParticipant.performRpc({
        destinationIdentity: 'voice-sell-agent',
        method: 'submit_lead_form',
        payload: JSON.stringify(data),
    });
};
```

#### 5.3 Webhook Processing
```python
# Agent processes form submission
async def submit_lead_form_handler(data: rtc.RpcInvocationData):
    lead_data = json.loads(data.payload)
    
    # Send to webhook
    async with aiohttp.ClientSession() as http_session:
        await http_session.post(WEBHOOK_URL, json=lead_data)
```

## Room Name Logic

### Main Page (`/`)
- **Room Name**: `voice_assistant_room_XXXX`
- **Agent Identity**: `voice-sell-agent`
- **Personality**: Default Voice Sell AI
- **Greeting**: "Thank you for calling Voice Sell AI. How can I help you today?"

### Devin Page (`/devin`)
- **Room Name**: `devin_voice_assistant_room_XXXX`
- **Agent Identity**: `voice-sell-agent`
- **Personality**: Ashley (Devin's personal assistant)
- **Greeting**: "Hi there! This is Ashley, Devin's personal assistant..."

## Environment Configuration

### Token Server (.env)
```env
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
```

### Agent (.env)
```env
LIVEKIT_URL=wss://your-livekit-server.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
DEEPGRAM_API_KEY=your_deepgram_api_key
GROQ_API_KEY=your_groq_api_key
CARTESIA_API_KEY=your_cartesia_api_key
WEBHOOK_URL=https://webhook.site/your-unique-webhook-url
BUSINESS_NAME=Voice Sell AI
KNOWLEDGE_BASE=VoiceSell provides audio systems using ai...
```

### Frontend (.env.local)
```env
NEXT_PUBLIC_LIVEKIT_URL=wss://your-livekit-server.livekit.cloud
```

## Security & Authentication

### JWT Token Structure
```python
token = AccessToken(API_KEY, API_SECRET)
token.with_identity(participant_identity)
token.with_name(participant_name)
token.with_grants(VideoGrants(
    room_join=True,
    room=room_name,
    can_publish=True,
    can_subscribe=True,
    can_publish_data=True,
))
```

### Room Access Control
- Each room has a unique name
- Participants can only join with valid JWT tokens
- Agents authenticate with LiveKit API credentials

## Error Handling

### Common Error Scenarios
1. **Token Expiration**: JWT tokens expire after 15 minutes
2. **Room Full**: LiveKit limits participants per room
3. **Network Issues**: WebRTC connection failures
4. **API Rate Limits**: Groq, Deepgram, Cartesia rate limits
5. **Agent Unavailable**: No agent running to handle requests

### Recovery Mechanisms
- Automatic token refresh
- Connection retry logic
- Graceful degradation
- Error logging and monitoring

## Performance Considerations

### Latency Optimization
- WebRTC for real-time audio
- Pre-warmed AI models
- Efficient audio processing
- Optimized network routing

### Scalability
- Stateless agent design
- Room-based isolation
- Load balancing ready
- Cloud-native architecture

## Monitoring & Logging

### Key Metrics
- Connection success rate
- Audio latency
- AI processing time
- Error rates
- User engagement

### Logging Levels
- **INFO**: Normal operations
- **WARNING**: Potential issues
- **ERROR**: System failures
- **DEBUG**: Detailed troubleshooting
