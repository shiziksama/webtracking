import asyncio
import contextlib
import json
import os
from contextlib import asynccontextmanager
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import FastAPI, WebSocket

from app.tracking import TrackingSession

NGROK_API_URL = os.getenv("NGROK_API_URL", "http://ngrok:4040/api/tunnels")
LOCAL_URL = os.getenv("LOCAL_URL", "http://localhost:8000")
NGROK_RETRY_SECONDS = 3


def fetch_ngrok_public_url() -> str | None:
    """Read the current HTTPS tunnel from the ngrok agent API."""
    try:
        with urlopen(NGROK_API_URL, timeout=2) as response:
            payload = json.load(response)
    except (OSError, URLError, TimeoutError, json.JSONDecodeError):
        return None

    public_urls = [
        tunnel.get("public_url")
        for tunnel in payload.get("tunnels", [])
        if isinstance(tunnel, dict)
    ]

    return next(
        (
            url
            for url in public_urls
            if isinstance(url, str) and url.startswith("https://")
        ),
        None,
    )


async def discover_ngrok_url(app: FastAPI) -> None:
    # Ngrok may start after the API, so discovery keeps retrying in background.
    while True:
        app.state.public_url = await asyncio.to_thread(fetch_ngrok_public_url)
        await asyncio.sleep(NGROK_RETRY_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.public_url = None
    discovery_task = asyncio.create_task(discover_ngrok_url(app))
    try:
        yield
    finally:
        discovery_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await discovery_task


app = FastAPI(title="Web Tracking API", lifespan=lifespan)


@app.get("/")
async def index() -> dict[str, str]:
    return {"name": "Web Tracking API", "status": "online"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/info")
async def info() -> dict[str, str | None]:
    public_url: str | None = app.state.public_url
    websocket_url = (
        f"{public_url.replace('https://', 'wss://', 1)}/ws/track"
        if public_url
        else None
    )

    return {
        "local_url": LOCAL_URL,
        "public_url": public_url,
        "websocket_url": websocket_url,
    }


@app.websocket("/ws/track")
async def track(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "status", "status": "idle"})
    session = TrackingSession()

    # Each WebSocket owns its frame and tracker, so clients never share state.
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return

        if message.get("bytes") is not None:
            # JPEG decoding and CSRT updates are CPU work; keep them off the event loop.
            response = await asyncio.to_thread(
                session.receive_frame,
                message["bytes"],
            )
            if response is not None:
                await websocket.send_json(response)
            continue

        text = message.get("text")
        if text is None:
            await websocket.send_json(
                {"type": "error", "message": "Unsupported WebSocket message"}
            )
            continue

        try:
            command = json.loads(text)
        except json.JSONDecodeError:
            await websocket.send_json(
                {"type": "error", "message": "Invalid JSON command"}
            )
            continue

        if not isinstance(command, dict) or command.get("type") != "select":
            await websocket.send_json(
                {"type": "error", "message": "Unsupported command"}
            )
            continue

        response = await asyncio.to_thread(session.select, command.get("bbox"))
        await websocket.send_json(response)
