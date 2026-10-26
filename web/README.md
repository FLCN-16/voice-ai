# Voice AI web console

This Next.js 16 App Router client asks Python for a session through
`POST /v1/sessions`, then connects to
`/v1/voice/{agent_name}/{session_id}`. The returned session ID is also the
conversation ID. It captures microphone audio as mono 16 kHz PCM16 frames,
sends them over WebSocket, renders canonical events, and plays streamed TTS
chunks when the browser permits audio playback.

## Configure

The client defaults to `http://localhost:8000`. To use another API origin:

```bash
cp .env.example .env.local
```

Then set:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Run

Install dependencies and run the development server:

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000), enter an agent name such
as `falcon`, and start a session. The browser will request microphone access.

Run the backend separately:

```bash
cd ../agents
uv run fastapi dev app/main.py
```

## Checks

```bash
npm run lint
npm run build
```
