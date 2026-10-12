#!/bin/bash
set -e

# Install any additional requirements
if [ -f "/app/requirements.txt" ]; then
    pip install --no-cache-dir -r /app/requirements.txt
fi

export MLFLOW_BACKEND_STORE_URI="${MLFLOW_BACKEND_STORE_URI}"
export MLFLOW_ARTIFACTS_DESTINATION="${MLFLOW_ARTIFACTS_DESTINATION}"
export MLFLOW_HOST="${MLFLOW_HOST}"
export MLFLOW_PORT="${MLFLOW_PORT}"
export MLFLOW_S3_ENDPOINT_URL="${MLFLOW_S3_ENDPOINT_URL}"
export MLFLOW_S3_IGNORE_TLS="${MLFLOW_S3_IGNORE_TLS}"
export DEFAULT_MLFLOW_PERMISSIONS="${DEFAULT_MLFLOW_PERMISSIONS}"
export AUTOMATIC_LOGIN_REDIRECT="${AUTOMATIC_LOGIN_REDIRECT}"
export MLFLOW_SERVER_ALLOWED_HOSTS="${MLFLOW_SERVER_ALLOWED_HOSTS}"

echo "========================================"
echo "Starting MLflow with configuration:"
echo "  Backend Store URI:      $MLFLOW_BACKEND_STORE_URI"
echo "  Artifacts Destination:  $MLFLOW_ARTIFACTS_DESTINATION"
echo "  S3 Endpoint URL:        $MLFLOW_S3_ENDPOINT_URL"
echo "  Host:                   $MLFLOW_HOST"
echo "  Port:                   $MLFLOW_PORT"
echo "  OIDC Discovery URL:     $OIDC_DISCOVERY_URL"
echo "  OIDC Client ID:         $OIDC_CLIENT_ID"
echo "  OIDC Redirect URI:      $OIDC_REDIRECT_URI"
echo "  Allowed Hosts:          $MLFLOW_SERVER_ALLOWED_HOSTS"
echo "========================================"

exec mlflow server \
    --app-name oidc-auth \
    --backend-store-uri "$MLFLOW_BACKEND_STORE_URI" \
    --serve-artifacts \
    --artifacts-destination "$MLFLOW_ARTIFACTS_DESTINATION" \
    --host "$MLFLOW_HOST" \
    --port "$MLFLOW_PORT"