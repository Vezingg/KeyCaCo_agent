#!/bin/bash
# start-web.sh — Entrypoint for the College Search Agent container.
#
# Starts two processes:
#   1. FastWorkflow  (port 8000, internal) — the AI agent API
#   2. main.py       (port 8080, public)   — web chatbot + WhatsApp webhook
#
# Cloud Run only exposes port 8080.
# Routes:
#   /              → web chatbot
#   /webhooks/*    → WhatsApp webhook
#   /health        → health check
set -e

# ── 1. FastWorkflow ──────────────────────────────────────────────────────────
start_fastworkflow() {
    echo "[start] Starting FastWorkflow on port 8000..."
    fastworkflow run_fastapi_mcp \
        /app/college_search_agent \
        /app/college_search_agent/fastworkflow.env \
        /app/college_search_agent/fastworkflow.passwords.env \
        --host 0.0.0.0 \
        --port 8000 &
    FASTWORKFLOW_PID=$!
    echo "[start] FastWorkflow PID: $FASTWORKFLOW_PID"
}

start_fastworkflow

# ── 2. Wait until FastWorkflow is healthy (no limit — just keep polling) ────
echo "[start] Waiting for FastWorkflow to be ready (no timeout)..."
SECONDS_WAITED=0
until curl -s http://localhost:8000/ > /dev/null 2>&1; do
    sleep 3
    SECONDS_WAITED=$((SECONDS_WAITED + 3))
    echo "[start] Still waiting... (${SECONDS_WAITED}s elapsed)"
done

echo "[start] FastWorkflow is ready after ${SECONDS_WAITED}s!"

# ── 3. Watchdog — restart FastWorkflow if it crashes ────────────────────────
(
    while true; do
        sleep 5
        if ! kill -0 $FASTWORKFLOW_PID 2>/dev/null; then
            echo "[watchdog] FastWorkflow (PID $FASTWORKFLOW_PID) crashed — restarting..."
            start_fastworkflow
            until curl -s http://localhost:8000/ > /dev/null 2>&1; do sleep 2; done
            echo "[watchdog] FastWorkflow restarted (PID $FASTWORKFLOW_PID)"
        fi
    done
) &

# ── 4. Combined server — web chatbot + WhatsApp webhook (foreground) ─────────
echo "[start] Starting combined server on port 8080..."
exec uvicorn college_search_agent.application.main:app \
    --host 0.0.0.0 \
    --port 8080 \
    --workers 1
