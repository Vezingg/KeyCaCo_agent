#!/bin/bash
# deploy-web-gcp.sh — Build, push, and deploy the College Search Agent to Cloud Run.
#
# Deploys a single service that serves:
#   /              → web chatbot
#   /webhooks/*    → WhatsApp webhook
#   /health        → health check
#
# Usage:
#   ./deploy-web-gcp.sh              — full: build + deploy
#   ./deploy-web-gcp.sh --deploy-only — skip build, just deploy existing image
#
# Prerequisites:
#   • gcloud CLI installed and authenticated (gcloud auth login)
#   • WhatsApp credentials set as env vars or hardcoded below
set -e

DEPLOY_ONLY=false
if [[ "${1}" == "--deploy-only" ]]; then
    DEPLOY_ONLY=true
fi

# ── Project settings ─────────────────────────────────────────────────────────
PROJECT_ID="keycaco"
PROJECT_NUMBER="$(gcloud projects describe keycaco --format='value(projectNumber)')"
REGION="asia-south1"
SERVICE="college-search-web"
REPO="agent-repo"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:latest"

# ── Firebase (optional — enables permanent chat history in web chatbot) ──────
# Set FIREBASE_PROJECT_ID to your Firebase project ID.
# Leave as empty string to skip — the chatbot still works, history just isn't permanent.
FIREBASE_PROJECT_ID="${FIREBASE_PROJECT_ID:-keycaco}"

# ── WhatsApp credentials (read from env or set here) ────────────────────────
# These are passed as Cloud Run env vars (NOT baked into the image).
# Either export them before running this script, or set them below.
WHATSAPP_PHONE_NUMBER_ID="${WHATSAPP_PHONE_NUMBER_ID:-}"
WHATSAPP_ACCESS_TOKEN="${WHATSAPP_ACCESS_TOKEN:-}"
WHATSAPP_VERIFY_TOKEN="${WHATSAPP_VERIFY_TOKEN:-college_verify_2024}"

# ── Checks ───────────────────────────────────────────────────────────────────
if ! command -v gcloud &>/dev/null; then
    echo "Error: 'gcloud' not found. Please install it and try again."
    exit 1
fi

echo "============================================================"
echo " College Search Agent — Deployment"
echo "============================================================"
echo " GCP Project  : ${PROJECT_ID} (${PROJECT_NUMBER})"
echo " Region       : ${REGION}"
echo " Service      : ${SERVICE}"
echo " Image        : ${IMAGE}"
echo " Firebase ID  : ${FIREBASE_PROJECT_ID:-<not set>}"
echo " WA Phone ID  : ${WHATSAPP_PHONE_NUMBER_ID:-<not set — update after deploy>}"
echo " WA Verify Tok: ${WHATSAPP_VERIFY_TOKEN}"
echo "============================================================"
echo ""

# ── GCP project setup ────────────────────────────────────────────────────────
gcloud config set project "${PROJECT_ID}"
gcloud config set run/region "${REGION}"

echo "[gcp] Enabling required APIs..."
gcloud services enable \
    run.googleapis.com \
    artifactregistry.googleapis.com \
    secretmanager.googleapis.com \
    --quiet

# ── Artifact Registry ────────────────────────────────────────────────────────
echo "[gcp] Ensuring Artifact Registry repository exists..."
gcloud artifacts repositories create "${REPO}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="College Search Agent images" \
    2>/dev/null || true

gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# ── Cloud Build: build + push (skipped with --deploy-only) ─────────────────
if [[ "$DEPLOY_ONLY" == "true" ]]; then
    echo "[cloudbuild] Skipping build (--deploy-only mode)."
else
    echo "[cloudbuild] Submitting build (this may take 10-15 minutes)..."
    gcloud builds submit \
        --config=cloudbuild-web.yaml \
        --project="${PROJECT_ID}" \
        .
fi

# ── Secret Manager helpers ───────────────────────────────────────────────────
# Usage: store_secret <secret-name> <value>
store_secret() {
    local name="$1" value="$2"
    if gcloud secrets describe "$name" --project="${PROJECT_ID}" &>/dev/null; then
        echo "[secret] Updating '${name}'..."
        echo -n "$value" | gcloud secrets versions add "$name" \
            --data-file=- --project="${PROJECT_ID}"
    else
        echo "[secret] Creating '${name}'..."
        echo -n "$value" | gcloud secrets create "$name" \
            --data-file=- --project="${PROJECT_ID}"
    fi
}

# Store Firebase project id as a secret so the container can use it at runtime
if [[ -n "$FIREBASE_PROJECT_ID" ]]; then
    store_secret "firebase_project_id" "${FIREBASE_PROJECT_ID}"
fi

# Store WhatsApp credentials as secrets
if [[ -n "$WHATSAPP_PHONE_NUMBER_ID" ]]; then
    store_secret "whatsapp_phone_number_id" "${WHATSAPP_PHONE_NUMBER_ID}"
fi
if [[ -n "$WHATSAPP_ACCESS_TOKEN" ]]; then
    store_secret "whatsapp_access_token" "${WHATSAPP_ACCESS_TOKEN}"
fi
if [[ -n "$WHATSAPP_VERIFY_TOKEN" ]]; then
    store_secret "whatsapp_verify_token" "${WHATSAPP_VERIFY_TOKEN}"
fi

# Grant Cloud Run SA access to secrets
CR_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
echo "[iam] Granting Secret Manager access to Cloud Run service account..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CR_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet 2>/dev/null || true

# ── Cloud Run deployment ─────────────────────────────────────────────────────
echo "[cloudrun] Deploying service '${SERVICE}'..."

# Build --update-secrets flags
SECRET_FLAGS=""
if [[ -n "$FIREBASE_PROJECT_ID" ]]; then
    SECRET_FLAGS="${SECRET_FLAGS} --update-secrets=FIREBASE_PROJECT_ID=firebase_project_id:latest"
fi
if [[ -n "$WHATSAPP_PHONE_NUMBER_ID" ]]; then
    SECRET_FLAGS="${SECRET_FLAGS} --update-secrets=WHATSAPP_PHONE_NUMBER_ID=whatsapp_phone_number_id:latest"
fi
if [[ -n "$WHATSAPP_ACCESS_TOKEN" ]]; then
    SECRET_FLAGS="${SECRET_FLAGS} --update-secrets=WHATSAPP_ACCESS_TOKEN=whatsapp_access_token:latest"
fi
if [[ -n "$WHATSAPP_VERIFY_TOKEN" ]]; then
    SECRET_FLAGS="${SECRET_FLAGS} --update-secrets=WHATSAPP_VERIFY_TOKEN=whatsapp_verify_token:latest"
fi

gcloud run deploy "${SERVICE}" \
    --image "${IMAGE}" \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 1 \
    --port 8080 \
    --timeout 300 \
    --set-env-vars "FASTWORKFLOW_URL=http://localhost:8000,WEB_PORT=8080" \
    ${SECRET_FLAGS}

# ── Results ──────────────────────────────────────────────────────────────────
SERVICE_URL=$(gcloud run services describe "${SERVICE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format="value(status.url)")

echo ""
echo "============================================================"
echo " Deployment complete!"
echo "============================================================"
echo " Service URL    : ${SERVICE_URL}"
echo " Web Chatbot    : ${SERVICE_URL}/"
echo " WhatsApp Hook  : ${SERVICE_URL}/webhooks/whatsapp"
echo " Health check   : ${SERVICE_URL}/health"
echo "============================================================"
echo ""
echo "Next steps:"
echo "  1. Open ${SERVICE_URL}/ to verify the web chatbot loads."
echo "  2. Set this as your WhatsApp webhook URL in Meta Business Suite:"
echo "     ${SERVICE_URL}/webhooks/whatsapp"
echo "     Verify token: ${WHATSAPP_VERIFY_TOKEN}"
echo "  3. If WhatsApp credentials were not set, store them as secrets then re-deploy:"
echo "     echo -n '<phone_number_id>' | gcloud secrets versions add whatsapp_phone_number_id --data-file=-"
echo "     echo -n '<access_token>'    | gcloud secrets versions add whatsapp_access_token --data-file=-"
echo "     echo -n 'college_verify_2024' | gcloud secrets versions add whatsapp_verify_token --data-file=-"
echo "     Then run: ./deploy-web-gcp.sh --deploy-only"
echo "  4. If Firebase is not yet configured, edit:"
echo "     college_search_agent/application/website/firebase-config.js"
echo "     Replace the YOUR_... placeholders with your Firebase credentials,"
echo "     then rebuild and redeploy."
echo ""
