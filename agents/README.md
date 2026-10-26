# Voice AI

Voice AI is a FastAPI application for dynamically selected LangChain agents,
MongoDB-backed conversations, and provider-independent streaming voice
sessions.

## Features

- Dynamic agent discovery under `app/agents`.
- HTTP agent queries with conversation persistence.
- Conversation read and delete endpoints.
- One client WebSocket for audio input, STT, agent execution, TTS, and output
  events.
- Sarvam realtime STT and streaming TTS adapters.
- Cal.com availability and appointment-booking tools for Falcon.
- Canonical application events that hide provider-specific event names.
- Extensible base contracts for Sarvam, ElevenLabs, and future providers.

## Requirements

- Python 3.14 or newer.
- `uv`.
- MongoDB when persistent conversation storage is enabled.
- An API key for the selected model provider.
- `SARVAM_API_KEY` for Sarvam voice sessions.

## Setup

Install dependencies and create the project environment:

```powershell
uv sync
```

Create a `.env` file or configure environment variables in the shell:

```env
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=voice_ai
MONGODB_COLLECTION=conversations
# MongoDB is disabled by default; set this to true for persistent storage.
MONGODB_ENABLED=false

FALCON_MODEL=sarvam-105b
# Optional override; the default is app/agents/falcon/system_prompt.md.
FALCON_SYSTEM_PROMPT=You are Falcon, a concise voice assistant.

SARVAM_API_KEY=<your-sarvam-key>
SARVAM_LANGUAGE_CODE=en-IN
SARVAM_TTS_MODEL=bulbul:v3
SARVAM_TTS_SPEAKER=ratan
CALCOM_API_KEY=cal_...
CALCOM_API_BASE_URL=https://api.cal.com
CALCOM_SLOTS_API_VERSION=2024-09-04
CALCOM_BOOKINGS_API_VERSION=2026-02-25
CALCOM_TIMEOUT_SECONDS=20
CALCOM_DEFAULT_EVENT_TYPE_ID=123
CALCOM_DEFAULT_TIME_ZONE=UTC
CALCOM_DEFAULT_DURATION_MINUTES=30
VOICE_INACTIVITY_PROMPT_AFTER_SECONDS=3
VOICE_INACTIVITY_HANGUP_AFTER_SECONDS=5
VOICE_INACTIVITY_PROMPT=Are you still there?
VOICE_PLAYBACK_ACK_TIMEOUT_SECONDS=60
VOICE_HANGUP_GRACE_SECONDS=2.5
LOG_LEVEL=INFO
```

The complete Cal.com configuration example is in
`app/agents/falcon/tools/calcom/.env.example`.

With MongoDB disabled, conversations are kept in memory for the lifetime of the
API process. Set `MONGODB_ENABLED=true` to use the configured MongoDB instance.

Configure the credentials required by the selected LangChain model provider.
Never commit `.env` or API keys.

Run the API:

```powershell
uv run fastapi dev app/main.py
```

Run the Next.js voice console in a second terminal:

```powershell
cd ../web
npm run dev
```

Open `http://localhost:3000` and start a session with the `falcon` agent. The
web client connects to `WS /v1/voice/{agent_name}/{conversation_id}` and sends
browser microphone audio as 16 kHz PCM16 frames. Set
`web/.env.local` with `NEXT_PUBLIC_API_URL` when the API is not at
`http://localhost:8000`.

The health endpoint is available at `http://localhost:8000/health`.

## Project structure

```text
app/
├── agents/                 # Dynamically discovered AI agents
│   ├── registry.py
│   └── falcon/              # Includes Cal.com appointment tools
├── controllers/            # Categorized HTTP/WebSocket routes
│   ├── agents.py
│   ├── conversations.py
│   ├── health.py
│   └── voice.py
├── database/               # MongoDB client, models, and repositories
│   ├── dbs/
│   ├── models/
│   └── repositories/
├── voice/                  # Voice contracts, events, and provider adapters
│   ├── agent.py
│   ├── base.py
│   ├── events.py
│   └── sarvam/
├── main.py
└── __init__.py
```

## HTTP API

### Health

```http
GET /health
```

Returns application status and discovered agents:

```json
{
  "status": "ok",
  "agents": ["falcon"]
}
```

### Create a session

Create a server-owned session before starting a chat or voice interaction:

```http
POST /v1/sessions
Content-Type: application/json
```

Request:

```json
{
  "agent_name": "falcon",
  "mode": "voice"
}
```

Response:

```json
{
  "session_id": "2d4c...",
  "conversation_id": "2d4c...",
  "agent": "falcon",
  "mode": "voice"
}
```

The Python service creates the session ID. The same value is used as the
conversation ID for history loading and persistence.

### Query an agent

```http
POST /v1/agent/{agent_name}/query
Content-Type: application/json
```

Request:

```json
{
  "session_id": "2d4c...",
  "messages": [
    {
      "role": "user",
      "content": "What time is it?"
    }
  ]
}
```

Use the `session_id` returned by `POST /v1/sessions` for every request in the
same chat. The API returns the same value as `conversation_id`:

```json
{
  "agent": "falcon",
  "session_id": "2d4c...",
  "conversation_id": "2d4c...",
  "response": "..."
}
```

The same conversation ID loads previous messages and appends the new user and
assistant messages to MongoDB.

### Get a conversation

```http
GET /v1/conversations/{conversation_id}
```

Returns conversation metadata and ordered messages. Returns `404` when the
conversation does not exist.

### Delete a conversation

```http
DELETE /v1/conversations/{conversation_id}
```

Deletes the complete conversation and returns `204 No Content`. Returns `404`
when the conversation does not exist.

## Voice WebSocket

The voice endpoint exposes one application-facing WebSocket:

```text
WS /v1/voice/{agent_name}/{session_id}
```

The server internally coordinates:

1. The Python-created session ID is used as the conversation ID.
2. Sarvam STT.
2. The dynamically selected agent.
3. Sarvam TTS.
5. MongoDB conversation persistence.

The client sends base64 audio:

```json
{
  "type": "audio",
  "audio": "<base64-audio>"
}
```

End the session:

```json
{
  "type": "stop"
}
```

The server sends canonical events such as `speech.started`,
`transcript.final`, `audio.output`, `agent.started`, and `agent.completed`.
Provider event names are not part of the application control flow.

Every agent response, including the inactivity prompt, includes a unique
`response_id`. After the browser finishes playing that response, it sends
`{"type":"playback.completed","response_id":"..."}`. The server starts
its inactivity timer only after the matching acknowledgement, so a long
response is not interrupted while it is still playing.
If the browser does not acknowledge playback, the server falls back after
`VOICE_PLAYBACK_ACK_TIMEOUT_SECONDS` so the silence timer cannot remain
disabled indefinitely.

After session start and after each completed agent reply, the voice runtime
waits for caller activity. By default it asks `Are you still there?` after
three seconds and hangs up after five seconds without speech. Speech or a
final transcript resets this timer. The timings and prompt can be changed with
the `VOICE_INACTIVITY_*` settings above.

Voice-capable agents receive the shared `hangup_call` tool. When an agent uses
it, it must provide a short `goodbye` in the current conversation language.
That text is synthesized and the runtime emits `call.hangup` before closing
the call.
The runtime waits briefly after synthesis before closing the client socket so
the browser can finish playing buffered goodbye audio. Configure that delay
with `VOICE_HANGUP_GRACE_SECONDS`.

## Canonical voice events

`app/voice/events.py` defines the application-level event contract:

```text
session.started
session.ended
audio.input
audio.output
speech.started
speech.ended
transcript.partial
transcript.final
config.updated
keepalive
synthesis.completed
agent.started
agent.completed
call.hangup
error
provider
```

Provider adapters translate their wire events into these common types:

```python
VoiceEvent.from_provider(
    provider="sarvam",
    provider_event="vad.speech_start",
    type=VoiceEventType.SPEECH_STARTED,
    data=payload,
)
```

The original `provider` and `provider_event` values are retained for
observability. Application code should branch on `VoiceEventType`, not on
Sarvam or ElevenLabs event names.

## Voice provider adapters

The base contracts are in `app/voice/base.py`:

- `BaseSTTModel` for audio-to-transcript providers.
- `BaseSSTModel` for text-to-audio streaming providers.
- `BaseVoiceModel` for shared session lifecycle.

Sarvam adapters are available in `app/voice/sarvam`:

```python
from agents.app import SarvamSTT, SarvamTTS

stt = SarvamSTT(
  session_id="call-1",
  language_code="hi-IN",
)

tts = SarvamTTS(
  session_id="call-1",
  model="bulbul:v3",
  speaker="ratan",
  language_code="en-IN",
)
```

Sarvam endpoints:

```text
wss://api.sarvam.ai/speech-to-text/ws
wss://api.sarvam.ai/text-to-speech/ws
```

Both adapters accept an injected WebSocket for tests or integration with an
existing provider connection. The application calls `load_dotenv()` during
startup, so values from the project-root `.env` file are loaded automatically.
Variables already set in the shell take precedence. Set `SARVAM_API_KEY`
before opening the voice socket.

## Database layout

```text
app/database/
├── dbs/
│   └── mongodb.py
├── models/
│   └── conversation.py
└── repositories/
    └── conversations.py
```

`MongoDatabase` owns the async client and connection lifecycle.
`ConversationDocument` and `MessageDocument` define stored document shapes.
`ConversationRepository` owns conversation reads, writes, and deletes.

## Validation

Run the available checks with:

```powershell
uv run python -m compileall -q app
git --no-pager diff --check
```

Provider adapters should be tested with injected fake WebSockets. Tests should
verify both the provider wire payload and the canonical event emitted to the
application.
