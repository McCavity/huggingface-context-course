import datetime as dt
from collections import Counter, deque
from typing import Any

import gradio as gr
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# ---------- Shared state ----------
MAX_EVENTS = 500
PORT=8001
events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)


def _truncate(value: Any, n: int) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= n else text[: n - 1] + "…"


def _normalize(body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    """Map Claude Code / Codex / OpenCode / Pi payloads to one shape."""
    platform = (
        body.get("platform")
        or headers.get("x-platform")
        or "unknown"
    )
    event_name = body.get("event") or body.get("hook_event_name") or "Unknown"
    tool = body.get("tool") or body.get("tool_name") or ""
    args = body.get("args") or body.get("tool_input") or body.get("prompt") or ""
    return {
        "timestamp": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "platform": str(platform),
        "event": str(event_name),
        "tool": str(tool),
        "args": _truncate(args, 200),
    }


# ---------- FastAPI receiver ----------
api = FastAPI(title="Agent Activity Dashboard")


@api.post("/event")
async def event(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    record = _normalize(body, {k.lower(): v for k, v in req.headers.items()})
    events.appendleft(record)
    # Return an empty body so hook callers never block on the dashboard receiver.
    return JSONResponse({})


@api.get("/health")
def health():
    return {"ok": True, "events": len(events)}


# ---------- Gradio views ----------
COLUMNS = ["timestamp", "platform", "event", "tool", "args"]


def events_df() -> pd.DataFrame:
    if not events:
        return pd.DataFrame(columns=COLUMNS)
    return pd.DataFrame(list(events), columns=COLUMNS)


def tool_counts_df() -> pd.DataFrame:
    counter = Counter(e["tool"] for e in events if e["tool"])
    rows = [{"tool": tool, "count": n} for tool, n in counter.most_common(15)]
    return pd.DataFrame(rows, columns=["tool", "count"])


def summary_md() -> str:
    total = len(events)
    platforms = sorted({e["platform"] for e in events}) or ["(none)"]
    tools = sorted({e["tool"] for e in events if e["tool"]})
    tools_display = ", ".join(tools) if tools else "(none)"
    return (
        f"**Events:** {total} (buffer holds up to {MAX_EVENTS})  \n"
        f"**Platforms seen:** {', '.join(platforms)}  \n"
        f"**Tools seen:** {tools_display}"
    )


def refresh():
    return events_df(), tool_counts_df(), summary_md()


def clear_events():
    events.clear()
    return refresh()


with gr.Blocks(title="Agent Activity Dashboard") as ui:
    gr.Markdown("# Agent Activity Dashboard")
    gr.Markdown(
        "Point your Claude Code, Codex, OpenCode, or Pi hooks/extensions at "
        "`POST http://localhost:" + str(PORT) + "/event` to see live activity here."
    )

    header = gr.Markdown(value=summary_md())

    with gr.Row():
        clear_btn = gr.Button("Clear events", variant="secondary")

    chart = gr.BarPlot(
        value=tool_counts_df(),
        x="tool",
        y="count",
        title="Tool usage",
        tooltip=["tool", "count"],
        height=280,
    )

    table = gr.Dataframe(
        value=events_df(),
        headers=COLUMNS,
        label="Recent events (newest first)",
        wrap=True,
        interactive=False,
    )

    # Poll the shared buffer once a second.
    gr.Timer(1.0).tick(refresh, outputs=[table, chart, header])
    clear_btn.click(clear_events, outputs=[table, chart, header])


# Mount Gradio on the FastAPI app so `/event` and the UI share one process.
app = gr.mount_gradio_app(api, ui, path="/")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
