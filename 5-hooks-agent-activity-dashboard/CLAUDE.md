# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A live dashboard that receives activity events from coding agents (Claude Code,
Codex, OpenCode, Pi) via their hook/extension systems and displays them in real
time. The entire app is one file: `app.py`.

## Run

```bash
source venv/bin/activate          # venv already exists in repo
pip install -r requirements.txt   # first time only
python app.py                     # serves on http://localhost:8001
```

There are no tests, linter config, or build step. Verify changes by running the
app and POSTing a sample event:

```bash
curl -X POST http://localhost:8001/event \
  -H 'Content-Type: application/json' -H 'X-Platform: claude-code' \
  -d '{"event":"PreToolUse","tool":"Bash","args":"ls"}'
curl http://localhost:8001/health   # -> {"ok": true, "events": N}
```

## Architecture

One process serves both the HTTP receiver and the UI. A FastAPI app (`api`)
defines the `/event` and `/health` routes; the Gradio Blocks UI (`ui`) is mounted
onto it at `/` via `gr.mount_gradio_app(api, ui, ...)`, producing the final `app`
that uvicorn runs. Both share the same in-process state.

State is a single module-level `deque(maxlen=MAX_EVENTS)` named `events` — an
in-memory ring buffer, **not persisted**. Restarting the app loses all events.
New events are `appendleft`ed (newest first).

`_normalize()` is the key glue: it maps the differently-shaped payloads from each
agent platform onto one common record (`timestamp`, `platform`, `event`, `tool`,
`args`). Platform is read from the body or the `X-Platform` header. When adding
support for a new agent, extend the `.get(...)` fallback chains here rather than
adding new branches elsewhere.

The UI polls the shared buffer once per second via `gr.Timer(1.0).tick(refresh)`;
there is no push/websocket. `refresh()` recomputes all three views (events table,
tool-usage bar chart, summary markdown) from the buffer on every tick.

`/event` always returns an empty `200` so that agent hooks never block waiting on
the dashboard — keep this contract; hook callers are in the request hot path.

## Wiring agents to the dashboard

`.claude/settings.json` registers Claude Code hooks (PreToolUse, PostToolUse,
UserPromptSubmit, Stop, SessionStart) as `http` hooks pointing at
`http://localhost:8001/event` with an `X-Platform: claude-code` header. Other
agents are pointed at the same endpoint via their own hook mechanisms.

The port is the `PORT` constant in `app.py` (8001). If you change it, update
`.claude/settings.json` hook URLs to match.
