"""
WhatsApp Cloud App for College Search Agent.
Handles WhatsApp webhook and routes messages to the FastWorkflow agent.
"""

import os
import re
import logging
import httpx
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Response
from typing import Dict


# ---------------------------------------------------------------------------
# Load env files
# ---------------------------------------------------------------------------
def _load_env_files() -> None:
    base_dir = Path(__file__).parent.parent  # college_search_agent/
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
# Logging & config
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("college_search_cloud_app")

VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "college_verify_2024")
PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")

# FastWorkflow runs locally in the same container
FASTWORKFLOW_URL = os.environ.get("FASTWORKFLOW_URL", "http://localhost:8000")

app = FastAPI(title="College Search WhatsApp Agent")

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------

# phone → FastWorkflow session data (access_token, etc.)
session_cache: Dict[str, dict] = {}

# phone → generation counter; incremented on "reset" to force a new channel_id
session_generation: Dict[str, int] = {}

# Deduplication: WhatsApp retries webhooks, so track processed message IDs
processed_message_ids: Dict[str, datetime] = {}

# ---------------------------------------------------------------------------
# Help message
# ---------------------------------------------------------------------------

HELP_MESSAGE = (
    "Here's what I can help you with:\n\n"
    "\U0001f393 Search Colleges \u2014 Ask about colleges by name, location, or type\n"
    "\U0001f4ca Filter by Marks \u2014 'Which colleges accept 85% marks?'\n"
    "\U0001f4b0 Filter by Fees \u2014 'Colleges with fees under 1 lakh'\n"
    "\U0001f4da Filter by Course \u2014 'Colleges offering B.Tech CS'\n"
    "\U0001f504 Reset \u2014 Say *reset* to start a fresh conversation\n\n"
    "Just type your question naturally!"
)

# ---------------------------------------------------------------------------
# WhatsApp API helpers
# ---------------------------------------------------------------------------

async def send_whatsapp(to: str, message: str) -> bool:
    """Send a text message via WhatsApp Cloud API."""
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
            logger.error(f"Failed to send message to {to}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"WhatsApp send error: {e}")
        return False


async def send_typing_indicator(to: str, msg_id: str) -> None:
    """Send a read receipt + typing indicator to the user."""
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
    except httpx.HTTPStatusError as exc:
        logger.error(f"Meta API rejected typing indicator: {exc.response.text}")
    except Exception as e:
        logger.warning(f"Typing indicator failed (non-critical): {e}")


# ---------------------------------------------------------------------------
# Markdown → WhatsApp formatter
# ---------------------------------------------------------------------------

def _md_table_to_whatsapp(table_lines: list) -> str:
    """Convert a markdown table block to a WhatsApp-friendly bullet list."""
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
            parts.append(f"• {row[0]}")
        return "\n".join(parts)

    rest_headers = headers[1:]
    for row in data_rows:
        name = row[0] if row else ""
        parts.append(f"*{name}*")
        for i, header in enumerate(rest_headers):
            value = row[i + 1] if i + 1 < len(row) else ""
            if value:
                parts.append(f"  • {header}: {value}")
        parts.append("")
    while parts and parts[-1] == "":
        parts.pop()
    return "\n".join(parts)


def markdown_to_whatsapp(text: str) -> str:
    """Convert Markdown formatting to WhatsApp-compatible formatting."""
    # Strip HTML tags
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)

    # Convert markdown tables
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

    # Headings → *bold*
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    # **bold** / __bold__ → *bold*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"*\1*", text, flags=re.DOTALL)
    # ~~strikethrough~~ → ~strikethrough~
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)
    # `inline code` → ```inline code```
    text = re.sub(r"(?<!`)`(?!`)([^`]+)(?<!`)`(?!`)", r"```\1```", text)
    # Remove markdown links [text](url) → text
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Horizontal rules → unicode divider
    text = re.sub(r"^[-*_]{3,}\s*$", "─" * 17, text, flags=re.MULTILINE)
    # Collapse 3+ blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# FastWorkflow session management
# ---------------------------------------------------------------------------

async def get_or_create_session(phone: str) -> dict:
    """Return an existing FastWorkflow session or create a new one."""
    if phone in session_cache:
        return session_cache[phone]

    gen = session_generation.get(phone, 0)
    channel_id = f"whatsapp_{phone}_v{gen}" if gen > 0 else f"whatsapp_{phone}"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{FASTWORKFLOW_URL}/initialize",
                json={"channel_id": channel_id, "user_id": phone},
            )
            if resp.status_code == 200:
                session_cache[phone] = resp.json()
                logger.info(f"Session created for {phone} (channel: {channel_id})")
                return session_cache[phone]
            logger.error(f"FastWorkflow init failed (HTTP {resp.status_code}): {resp.text}")
            return {}
    except Exception as e:
        logger.error(f"Session creation error for {phone}: {type(e).__name__}: {e}")
        return {}


async def chat_with_agent(phone: str, message: str) -> str:
    """Send a message to the FastWorkflow agent and return its text response."""
    is_new_session = phone not in session_cache
    session = await get_or_create_session(phone)
    if not session:
        return "I'm having trouble connecting to the agent. Please try again."

    headers: dict = {}
    token = session.get("access_token", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            # For brand-new sessions, silently initialize with phone context
            if is_new_session:
                await client.post(
                    f"{FASTWORKFLOW_URL}/invoke_agent",
                    json={
                        "user_query": f"initialize session for phone {phone}",
                        "timeout_seconds": 500,
                    },
                    headers=headers,
                )

            resp = await client.post(
                f"{FASTWORKFLOW_URL}/invoke_agent",
                json={"user_query": message, "timeout_seconds": 500},
                headers=headers,
            )

            if resp.status_code == 200:
                data = resp.json()
                responses = data.get("command_responses", [])
                return (
                    responses[0].get("response", "")
                    if responses
                    else data.get("response", "")
                )
            logger.error(f"Agent invoke failed (HTTP {resp.status_code}): {resp.text}")
            return "I'm having trouble processing that. Please try again."

    except Exception as e:
        logger.error(f"Agent chat error for {phone}: {type(e).__name__}: {e}")
        return "I'm having trouble connecting. Please try again."


# ---------------------------------------------------------------------------
# Deduplication cleanup
# ---------------------------------------------------------------------------

def _cleanup_processed_messages(max_age_minutes: int = 30) -> None:
    """Remove old message IDs to prevent memory growth."""
    cutoff = datetime.now() - timedelta(minutes=max_age_minutes)
    to_remove = [mid for mid, ts in processed_message_ids.items() if ts < cutoff]
    for mid in to_remove:
        del processed_message_ids[mid]


# ---------------------------------------------------------------------------
# Message handling
# ---------------------------------------------------------------------------

async def handle_customer_message(phone: str, text: str, msg_id: str = "") -> None:
    """Route an inbound customer message and reply."""
    stripped = text.strip().lower()

    # Built-in commands
    if stripped in {"help", "?", "menu"}:
        await send_whatsapp(phone, HELP_MESSAGE)
        return

    if stripped == "reset":
        if msg_id:
            await send_typing_indicator(phone, msg_id)
        response = await chat_with_agent(phone, "//reset")
        await send_whatsapp(phone, markdown_to_whatsapp(response) if response else "\U0001f504 Session reset!")
        return

    # Show typing indicator while the agent thinks
    if msg_id:
        await send_typing_indicator(phone, msg_id)

    response = await chat_with_agent(phone, text)
    if response:
        await send_whatsapp(phone, markdown_to_whatsapp(response))


# ---------------------------------------------------------------------------
# Webhook endpoints
# ---------------------------------------------------------------------------

@app.get("/webhooks/whatsapp")
async def verify_webhook(request: Request) -> Response:
    """WhatsApp webhook verification challenge."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return Response(content=challenge)

    logger.warning("Webhook verification failed")
    return Response(content="Forbidden", status_code=403)


@app.post("/webhooks/whatsapp")
async def webhook(request: Request) -> dict:
    """Handle incoming WhatsApp messages."""
    try:
        data = await request.json()

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                if "messages" not in value:
                    continue

                msg = value["messages"][0]
                phone = msg["from"]
                msg_id = msg.get("id", "")

                # Deduplicate repeated webhook deliveries
                if msg_id and msg_id in processed_message_ids:
                    logger.info(f"Skipping duplicate message {msg_id}")
                    return {"status": "ok"}
                if msg_id:
                    processed_message_ids[msg_id] = datetime.now()
                    _cleanup_processed_messages()

                if msg.get("type") == "text":
                    text = msg["text"]["body"]
                    logger.info(f"[{phone}] Text: {text}")
                    await handle_customer_message(phone, text, msg_id)

                elif msg.get("type") == "image":
                    logger.info(f"[{phone}] Inbound image (unsupported)")
                    await send_whatsapp(
                        phone,
                        "I received your image! For the best help, please describe your question in text. 😊"
                    )

    except Exception as e:
        logger.error(f"Webhook processing error: {e}")

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check() -> dict:
    """Basic health check."""
    return {
        "status": "healthy",
        "active_sessions": len(session_cache),
    }