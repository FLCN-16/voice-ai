# Project Guidelines

## Architecture

- Keep dynamic agents under `app`; follow
  [app/agents/README.md](app/agents/README.md).
- Every agent package must export a zero-argument
  `get_<name>_agent` factory from `__init__.py`. Do not add manual registry
  switches.
- Keep HTTP and WebSocket routes in categorized modules under
  `app/controllers`; register routers in `app`.
- Keep MongoDB clients, typed documents, and persistence operations separated
  under `app/database/dbs`, `app`, and
  `app`.
- Keep voice provider integrations under `app/voice`. Provider adapters must
  map provider-specific payloads to canonical `VoiceEventType` values.

## Agent and voice conventions

- Create model clients lazily so importing an agent does not require
  credentials.
- Keep conversation persistence in controllers/repositories, not inside
  individual agents.
- Branch on canonical events such as `SPEECH_STARTED`,
  `TRANSCRIPT_FINAL`, `AUDIO_OUTPUT`, and `SYNTHESIS_COMPLETED`; never branch
  on Sarvam or ElevenLabs event names.
- Preserve `provider` and `provider_event` on mapped events for diagnostics.
- Inject WebSockets into provider adapters for deterministic tests.
- Keep secrets in environment variables; never commit API keys.
- Load local development values from `.env` with `python-dotenv`; use
  `SARVAM_API_KEY` for Sarvam credentials and never hard-code the value.

## Build and validation

Install dependencies with:

```powershell
uv sync
```

Run the API with:

```powershell
uv run fastapi dev app/main.py
```

Before completing code changes, run the smallest relevant checks:

```powershell
uv run python -m compileall -q app
git --no-pager diff --check
```

Provider adapters should be tested with fake injected WebSockets, validating
both provider wire messages and canonical application events. Update
[README.md](README.md) when public endpoints, configuration, or architecture
changes.