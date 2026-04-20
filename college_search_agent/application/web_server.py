"""
Web server for College Search Chatbot.
Serves the chatbot website (ChatGPT-style) and proxies API requests to FastWorkflow.

Run with:
    uvicorn college_search_agent.application.web_server:app --port 8080
or:
    python -m college_search_agent.application.web_server
"""

import os
import logging
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Load env files (same approach as cloud_app.py)
# ---------------------------------------------------------------------------
def _load_env_files() -> None:
    base_dir = Path(__file__).parent.parent
    for env_file in [
        base_dir / "fastworkflow.env",
        base_dir / "fastworkflow.passwords.env",
    ]:
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key not in os.environ:
                            os.environ[key] = value


_load_env_files()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("web_server")

FASTWORKFLOW_URL = os.environ.get("FASTWORKFLOW_URL", "http://localhost:8000")
WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))
WEBSITE_DIR = Path(__file__).parent / "website"

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="College Search Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (CSS, JS, images, etc.)
app.mount("/static", StaticFiles(directory=str(WEBSITE_DIR)), name="static")

# In-memory store: web session_id -> FastWorkflow session data
# Lost on server restart — Frontend Firebase handles persistent history
_fw_sessions: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class NewSessionRequest(BaseModel):
    user_id: str = "web_user"


class ChatRequest(BaseModel):
    session_id: str
    message: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
async def root() -> FileResponse:
    """Serve the main chatbot page."""
    index = WEBSITE_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Website files not found")
    return FileResponse(str(index))


@app.post("/api/new-session")
async def new_session(req: NewSessionRequest) -> dict:
    """
    Create a new FastWorkflow session.
    Returns the session UUID that the frontend must include in subsequent /api/chat calls.
    """
    session_id = str(uuid.uuid4())
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{FASTWORKFLOW_URL}/initialize",
                json={"channel_id": session_id, "user_id": req.user_id},
            )
            if resp.status_code == 200:
                _fw_sessions[session_id] = resp.json()
                logger.info(f"Session created: {session_id}")
                return {"session_id": session_id}

            logger.error(
                f"FastWorkflow init failed (HTTP {resp.status_code}): {resp.text}"
            )
            raise HTTPException(
                status_code=500, detail="Failed to initialize agent session"
            )
    except httpx.RequestError as exc:
        logger.error(f"FastWorkflow connection error: {exc}")
        raise HTTPException(
            status_code=503, detail="Agent service is unavailable. Is FastWorkflow running?"
        )


@app.post("/api/chat")
async def chat(req: ChatRequest) -> dict:
    """
    Send a user message to the FastWorkflow agent and return its response.
    The session_id must have been created via /api/new-session.
    """
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    if req.session_id not in _fw_sessions:
        raise HTTPException(
            status_code=404,
            detail="Session not found. The server may have restarted — please start a new chat.",
        )

    session = _fw_sessions[req.session_id]
    headers: dict[str, str] = {}
    token = session.get("access_token", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{FASTWORKFLOW_URL}/invoke_agent",
                json={"user_query": req.message, "timeout_seconds": 500},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                responses = data.get("command_responses", [])
                text = (
                    responses[0].get("response", "")
                    if responses
                    else data.get("response", "")
                )
                return {"response": text}

            logger.error(
                f"Agent invoke failed (HTTP {resp.status_code}): {resp.text}"
            )
            raise HTTPException(status_code=500, detail="Agent returned an error")

    except httpx.RequestError as exc:
        logger.error(f"FastWorkflow connection error: {exc}")
        raise HTTPException(
            status_code=503, detail="Agent service is unavailable"
        )


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str) -> dict:
    """Remove a session from the in-memory store (called on chat deletion)."""
    _fw_sessions.pop(session_id, None)
    return {"status": "ok"}


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy", "active_sessions": len(_fw_sessions)}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    logger.info(f"Starting web server on port {WEB_PORT}")
    logger.info(f"FastWorkflow URL: {FASTWORKFLOW_URL}")
    logger.info(f"Website dir: {WEBSITE_DIR}")
    uvicorn.run(
        "college_search_agent.application.web_server:app",
        host="0.0.0.0",
        port=WEB_PORT,
        reload=False,
    )
