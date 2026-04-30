"""
Combined entry point for the College Search Agent container.

Mounts both apps on a single FastAPI instance so Cloud Run can serve
both the web chatbot and the WhatsApp webhook on port 8080:

  /              → web chatbot  (web_server.py)
  /webhooks/*    → WhatsApp webhook  (cloud_app.py)
  /health        → health check  (cloud_app.py)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from college_search_agent.application.web_server import app as web_app
from college_search_agent.application.cloud_app import app as whatsapp_app

# Root app — CORS for web clients
app = FastAPI(title="College Search Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount WhatsApp webhook routes directly (not as a sub-application so
# root-level /health and /webhooks/* paths are all registered at the top level)
for route in whatsapp_app.routes:
    app.routes.append(route)

# Mount the web chatbot — this catches everything else including /static and /
app.mount("/", web_app)
