"""
Webhook relay: MLflow → GitHub CI.

Receives POST requests from MLflow (event: model_version_alias.created),
verifies the HMAC signature, and forwards a repository_dispatch to GitHub
for any alias listed in TRIGGER_ALIASES.

Environment variables:
    WEBHOOK_SECRET        HMAC secret configured in the MLflow webhook (required)
    GITHUB_TOKEN          GitHub token with repo/workflow scope (required)
    GITHUB_REPO           Target repo, e.g. org/repo (required)
    TRIGGER_ALIASES       Comma-separated list of aliases that trigger a build
                          (default: "champion")
    MLFLOW_TRACKING_URI   Internal MLflow URL to fetch run_id (required)
    MLFLOW_RELAY_USERNAME MLflow service account username (required)
    MLFLOW_RELAY_PASSWORD MLflow service account password (required)
    MLFLOW_ARTIFACTS_DESTINATION  Bucket root behind mlflow-artifacts:/, e.g. s3://mlflow/ (required)
    PORT                  Listening port (default: 8080)
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import time

import requests
from fastapi import FastAPI, Header, HTTPException, Request, status

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

_MAX_AGE_SECONDS = 300  # reject replays older than 5 minutes


def _load_config() -> tuple[str, str, str, set[str], str, str, str, str]:
    """Read and validate required env vars at startup."""
    required = ("WEBHOOK_SECRET", "GITHUB_TOKEN", "GITHUB_REPO",
                "MLFLOW_TRACKING_URI", "MLFLOW_RELAY_USERNAME", "MLFLOW_RELAY_PASSWORD",
                "MLFLOW_ARTIFACTS_DESTINATION")
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    secret = os.environ["WEBHOOK_SECRET"]
    github_token = os.environ["GITHUB_TOKEN"]
    github_repo = os.environ["GITHUB_REPO"]
    raw_aliases = os.environ.get("TRIGGER_ALIASES", "champion")
    trigger_aliases = {a.strip() for a in raw_aliases.split(",") if a.strip()}
    mlflow_uri = os.environ["MLFLOW_TRACKING_URI"].rstrip("/")
    mlflow_user = os.environ["MLFLOW_RELAY_USERNAME"]
    mlflow_pass = os.environ["MLFLOW_RELAY_PASSWORD"]
    artifacts_dest = os.environ["MLFLOW_ARTIFACTS_DESTINATION"].rstrip("/")

    log.info("Trigger aliases: %s", sorted(trigger_aliases))
    log.info("Target repo: %s", github_repo)
    log.info("MLflow URI: %s", mlflow_uri)
    return (secret, github_token, github_repo, trigger_aliases,
            mlflow_uri, mlflow_user, mlflow_pass, artifacts_dest)


(_SECRET, _GITHUB_TOKEN, _GITHUB_REPO, _TRIGGER_ALIASES,
 _MLFLOW_URI, _MLFLOW_USER, _MLFLOW_PASS, _ARTIFACTS_DEST) = _load_config()

app = FastAPI()


def _mlflow_get(endpoint: str, model_name: str, version: str) -> dict:
    """GET a model-versions endpoint. Raises HTTPException if unreachable or not JSON 200."""
    try:
        resp = requests.get(
            f"{_MLFLOW_URI}/api/2.0/mlflow/model-versions/{endpoint}",
            params={"name": model_name, "version": version},
            auth=(_MLFLOW_USER, _MLFLOW_PASS),
            timeout=10,
            # a rejected login redirects to the OIDC page, which would look like a 200
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as exc:
        log.error("MLflow unreachable on %s: %s", endpoint, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"MLflow unreachable: {exc}")

    try:
        if resp.status_code != 200:
            raise ValueError
        return resp.json()
    except ValueError:
        log.error("MLflow %s failed: HTTP %s — %s", endpoint, resp.status_code, resp.text[:500])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MLflow model-versions/{endpoint} failed ({resp.status_code})",
        )


def _to_s3(artifact_uri: str) -> str:
    """Map the proxied mlflow-artifacts:/ scheme back to the real bucket path."""
    # ponytail: handles mlflow-artifacts:/path only, not the mlflow-artifacts://host/... form
    if artifact_uri.startswith("mlflow-artifacts:"):
        return f"{_ARTIFACTS_DEST}/{artifact_uri.split(':', 1)[1].lstrip('/')}"
    return artifact_uri


def _fetch_model_version(model_name: str, version: str) -> tuple[str, str]:
    """Fetch (run_id, S3 artifact URI) of a model version. Raises HTTPException if either is missing."""
    run_id = _mlflow_get("get", model_name, version).get("model_version", {}).get("run_id", "")
    artifact_uri = _mlflow_get("get-download-uri", model_name, version).get("artifact_uri", "")
    if not run_id or not artifact_uri:
        log.error("run_id=%r artifact_uri=%r for %s v%s", run_id, artifact_uri, model_name, version)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"run_id or artifact_uri not found in MLflow for model {model_name} version {version}",
        )

    s3_uri = _to_s3(artifact_uri)
    log.info("Fetched run_id=%s source=%s for model=%s version=%s", run_id, s3_uri, model_name, version)
    return run_id, s3_uri


def _verify_signature(delivery_id: str, timestamp: str, raw_body: bytes, signature_header: str) -> None:
    if not signature_header or not signature_header.startswith("v1,"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or malformed signature")

    received_b64 = signature_header[len("v1,"):]
    # MLflow signs: delivery_id.timestamp.payload (payload as utf-8 string)
    signed = f"{delivery_id}.{timestamp}.{raw_body.decode('utf-8')}".encode()
    expected = base64.b64encode(
        hmac.new(_SECRET.encode(), signed, hashlib.sha256).digest()
    ).decode()

    if not hmac.compare_digest(expected, received_b64):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")


def _check_replay(timestamp: str) -> None:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid timestamp")

    age = time.time() - ts
    if age > _MAX_AGE_SECONDS or age < -60:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook timestamp out of acceptable range")


def _dispatch_github(run_id: str, model_source: str, alias: str) -> None:
    payload = {
        "event_type": "mlflow-model-version",
        "client_payload": {
            "data": {
                "run_id": run_id,
                "source": model_source,
                "alias": alias,
            }
        },
    }

    resp = requests.post(
        f"https://api.github.com/repos/{_GITHUB_REPO}/dispatches",
        headers={
            "Authorization": f"Bearer {_GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        },
        json=payload,
        timeout=10,
    )

    if resp.status_code != 204:
        log.error("GitHub dispatch failed: HTTP %s — %s", resp.status_code, resp.text)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub dispatch failed ({resp.status_code}): {resp.text}",
        )


@app.post("/webhook")
async def receive_webhook(
    request: Request,
    x_mlflow_signature: str = Header(default=""),
    x_mlflow_delivery_id: str = Header(default=""),
    x_mlflow_timestamp: str = Header(default=""),
) -> dict:
    raw_body = await request.body()

    # DEBUG — à supprimer après diagnostic
    log.info("Headers reçus: signature=%s delivery_id=%s timestamp=%s",
             x_mlflow_signature[:20] if x_mlflow_signature else "VIDE",
             x_mlflow_delivery_id or "VIDE",
             x_mlflow_timestamp or "VIDE")
    log.info("Tous les headers: %s", dict(request.headers))

    _check_replay(x_mlflow_timestamp)
    _verify_signature(x_mlflow_delivery_id, x_mlflow_timestamp, raw_body, x_mlflow_signature)

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")

    # New payload format: { entity, action, timestamp, data: { name, version, alias, ... } }
    data = body.get("data", {})
    alias = data.get("alias") or body.get("alias", "")
    if alias not in _TRIGGER_ALIASES:
        log.info("Ignored event: alias '%s' not in trigger list", alias)
        return {"status": "ignored"}

    model_name = data.get("name", "unknown")
    model_version = data.get("version", "unknown")
    # The alias event only carries name/version/alias: run_id and location come from the API
    run_id, model_source = _fetch_model_version(model_name, model_version)

    log.info("Dispatching: model=%s version=%s alias=%s run_id=%s", model_name, model_version, alias, run_id)
    _dispatch_github(run_id, model_source, alias)

    return {
        "status": "dispatched",
        "model": model_name,
        "version": model_version,
        "alias": alias,
        "run_id": run_id,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
