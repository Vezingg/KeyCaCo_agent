"""
WhatsApp Cloud App for College Search Agent.
Handles WhatsApp webhook and routes messages to FastWorkflow agent.
"""

import os
import re
import asyncio
import logging
import httpx
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Response
from typing import Dict


# --- LOAD ENV FILES ---
def load_env_files():
    """Load environment variables from fastworkflow env files."""
    base_dir = Path(__file__).parent.parent
    env_files = [
        base_dir / "fastworkflow.env",
        base_dir / "fastworkflow.passwords.env",
    ]
    for env_file in env_files:
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

load_env_files()

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("college_search_cloud_app")

# --- CONFIG ---
VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "kalash_verify_2024")
PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")

FASTWORKFLOW_URL = "http://localhost:8000"

app = FastAPI(title="College Search WhatsApp Agent")

# Session cache: phone -> FastWorkflow session data
session_cache: Dict[str, dict] = {}

# Message deduplication: track processed WhatsApp message IDs
processed_message_ids: Dict[str, datetime] = {}


def cleanup_processed_messages(max_age_minutes: int = 30):
    """Remove old message IDs to prevent memory leak."""
    cutoff = datetime.now() - timedelta(minutes=max_age_minutes)
    to_remove = [mid for mid, ts in processed_message_ids.items() if ts < cutoff]
    for mid in to_remove:
        del processed_message_ids[mid]


# ---------------------------------------------------------------------------
# WhatsApp API
# ---------------------------------------------------------------------------

async def send_whatsapp(to: str, message: str) -> bool:
    """Send a WhatsApp text message."""
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                logger.info(f"Message sent to {to}")
                return True
            logger.error(f"Failed to send message: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"WhatsApp send error: {e}")
        return False


async def send_typing_indicator(to: str, msg_id: str):
    """Send read receipt + typing indicator via Meta Graph API."""
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": msg_id,
        "typing_indicator": {"type": "text"},
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            logger.info(f"Typing indicator sent for {to}")
    except httpx.HTTPStatusError as exc:
        logger.error(f"Meta API rejected typing indicator: {exc.response.text}")
    except Exception as e:
        logger.warning(f"Typing indicator failed (non-critical): {e}")


# ---------------------------------------------------------------------------
# FastWorkflow Integration
# ---------------------------------------------------------------------------

async def get_or_create_session(phone: str) -> dict:
    """Get or create a FastWorkflow session for the given phone number."""
    if phone in session_cache:
        return session_cache[phone]
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{FASTWORKFLOW_URL}/initialize",
                json={"channel_id": f"whatsapp_{phone}", "user_id": phone},
            )
            if resp.status_code == 200:
                data = resp.json()
                session_cache[phone] = data
                logger.info(f"Session created for {phone}")
                return data
            logger.error(f"Failed to initialize session (HTTP {resp.status_code}): {resp.text}")
            return {}
    except Exception as e:
        logger.error(f"Session creation error: {type(e).__name__}: {e}")
        return {}


async def chat_with_agent(phone: str, message: str) -> str:
    """Send a message to the FastWorkflow agent and return its response."""
    session = await get_or_create_session(phone)
    if not session:
        return "I'm having trouble connecting. Please try again."
    try:
        headers = {}
        token = session.get("access_token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{FASTWORKFLOW_URL}/invoke_agent",
                json={"user_query": message, "timeout_seconds": 500},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                command_responses = data.get("command_responses", [])
                if command_responses:
                    return command_responses[0].get("response", "")
                return data.get("response", "")
            logger.error(f"Agent error (HTTP {resp.status_code}): {resp.text}")
            return "I'm having trouble processing that. Please try again."
    except Exception as e:
        logger.error(f"Chat error: {type(e).__name__}: {e}")
        return "I'm having trouble connecting. Please try again."


# ---------------------------------------------------------------------------
# Markdown -> WhatsApp Formatter
# ---------------------------------------------------------------------------

def _md_table_to_whatsapp(table_lines: list) -> str:
    """Convert a markdown table block to WhatsApp bullet-point list."""
    rows = []
    for line in table_lines:
        line = line.strip().strip("|")
        if re.match(r"^[\s\-\|:]+$", line):
            continue
        cells = [c.strip() for c in line.split("|")]
        if cells:
            rows.append(cells)
    if not rows:
        return ""

    headers = rows[0]
    data_rows = rows[1:]

    if not data_rows:
        return "*" + " | ".join(headers) + "*"

    parts = []
    if len(headers) == 1:
        for row in data_rows:
            parts.append(f"* {row[0]}")
        return "\n".join(parts)

    rest_headers = headers[1:]
    for row in data_rows:
        name = row[0] if row else ""
        parts.append(f"*{name}*")
        for i, header in enumerate(rest_headers):
            value = row[i + 1] if i + 1 < len(row) else ""
            if value:
                parts.append(f"  * {header}: {value}")
        parts.append("")
    while parts and parts[-1] == "":
        parts.pop()
    return "\n".join(parts)


def markdown_to_whatsapp(text: str) -> str:
    """Convert Markdown formatting to WhatsApp-supported formatting."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)

    lines = text.split("\n")
    result_lines = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("|") and "|" in stripped[1:]:
            table_block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_block.append(lines[i])
                i += 1
            result_lines.append(_md_table_to_whatsapp(table_block))
        else:
            result_lines.append(lines[i])
            i += 1
    text = "\n".join(result_lines)

    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)
    text = re.sub(r"(?<!`)`(?!`)([^`]+)(?<!`)`(?!`)", r"```\1```", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"^[-*_]{3,}\s*$", "\u2500" * 17, text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Startup Warmup
# ---------------------------------------------------------------------------

async def _warmup_fastworkflow(retries: int = 10, delay: float = 5.0):
    """Pre-initialize FastWorkflow on startup so the first real user gets a fast response."""
    _WARMUP_PHONE = "__warmup__"
    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(
                    f"{FASTWORKFLOW_URL}/initialize",
                    json={"channel_id": "warmup_session", "user_id": _WARMUP_PHONE},
                )
            if resp.status_code == 200:
                session_cache[_WARMUP_PHONE] = resp.json()
                logger.info("FastWorkflow warmup complete — models are loaded and ready.")
                return
            logger.warning(f"Warmup attempt {attempt}/{retries} failed (HTTP {resp.status_code}). Retrying in {delay}s...")
        except Exception as e:
            logger.warning(f"Warmup attempt {attempt}/{retries} error: {e}. Retrying in {delay}s...")
        await asyncio.sleep(delay)
    logger.error("FastWorkflow warmup gave up after all retries. First user query may be slow.")


@app.on_event("startup")
async def startup_event():
    """Kick off FastWorkflow warmup in the background when the app starts."""
    asyncio.create_task(_warmup_fastworkflow())
    logger.info("Startup: FastWorkflow warmup task scheduled.")


# ---------------------------------------------------------------------------
# Message Handler
# ---------------------------------------------------------------------------

async def handle_message(phone: str, text: str, msg_id: str = ""):
    """Handle an incoming WhatsApp message: show typing, call agent, reply."""
    try:
        logger.info(f"[{phone}] Received: {text}")

        if msg_id:
            await send_typing_indicator(phone, msg_id)

        response = await chat_with_agent(phone, text)

        if response:
            await send_whatsapp(phone, markdown_to_whatsapp(response))

    except Exception as e:
        logger.error(f"Error handling message from {phone}: {e}")
        await send_whatsapp(phone, "Sorry, I encountered an error. Please try again.")


# ---------------------------------------------------------------------------
# Webhook Endpoints
# ---------------------------------------------------------------------------

@app.get("/webhooks/whatsapp")
async def verify_webhook(request: Request):
    """WhatsApp webhook verification (GET challenge)."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return Response(content=challenge)

    logger.warning(f"Webhook verification failed. Mode: {mode}, Token match: {token == VERIFY_TOKEN}")
    return Response(content="Forbidden", status_code=403)


@app.post("/webhooks/whatsapp")
async def webhook(request: Request):
    """Receive incoming WhatsApp messages."""
    try:
        data = await request.json()

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                if "messages" in value:
                    msg = value["messages"][0]

                    if msg.get("type") == "text":
                        phone = msg["from"]
                        text = msg["text"]["body"]
                        msg_id = msg.get("id", "")

                        # Deduplicate: skip WhatsApp retries
                        if msg_id and msg_id in processed_message_ids:
                            logger.info(f"Skipping duplicate message {msg_id}")
                            return {"status": "ok"}

                        if msg_id:
                            processed_message_ids[msg_id] = datetime.now()
                            cleanup_processed_messages()

                        await handle_message(phone, text, msg_id)

    except Exception as e:
        logger.error(f"Webhook processing error: {e}")

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "active_sessions": len(session_cache),
    }
