# MLflow → GitHub CI — Webhook setup

## How it works

```
MLflow (model promoted to @champion)
  → POST /webhook  →  webhook-relay container → POST /repos/.../dispatches  →  GitHub Actions
```

When someone sets the `@champion` alias on a model version in MLflow, MLflow fires a webhook. The `webhook-relay` service receives it, verifies the HMAC signature, and triggers a `repository_dispatch` event on GitHub — which starts your CI pipeline.

---

## 1. Deploy the stack

All commands below are run from the repository root. Copy and fill in the env file:

```bash
cp .env.template .env
# edit .env — fill in all the WEBHOOK_* and GITHUB_* values
```

Build and start everything:

```bash
docker compose build webhook-relay
docker compose up -d
```

Check the relay is running:

```bash
docker compose ps webhook-relay
docker compose logs webhook-relay
```

---

## 2. Create the webhook in MLflow

Install the dependency once:

```bash
pip install mlflow
```

Point the script at your MLflow instance:

```bash
export MLFLOW_TRACKING_URI=https://mlflow.your-domain.org
export MLFLOW_TRACKING_USERNAME=your-user   # if auth is enabled
export MLFLOW_TRACKING_PASSWORD=your-pass
```

Create the webhook — the URL is the relay's `/webhook` endpoint:

```bash
python webhook_relay/manage_webhooks.py create \
  --url http://webhook-relay:8080/webhook \
  --name champion-ci-trigger
```

> If you run this from outside the Docker network, use the host-mapped port instead:
> `--url http://localhost:8080/webhook`

The script will print a generated HMAC secret:

```
Generated secret : 4f3a...
⚠️  Save this secret — set it in your endpoint as MLFLOW_WEBHOOK_SECRET
```

Copy that secret into your `.env` as `WEBHOOK_SECRET`, then restart the relay:

```bash
docker compose restart webhook-relay
```

---

## 3. Verify

List registered webhooks:

```bash
python webhook_relay/manage_webhooks.py list
```

Send a test payload:

```bash
python webhook_relay/manage_webhooks.py test --id <webhook_id>
```

A successful test returns `HTTP 200` from the relay. Check the relay logs to confirm:

```bash
docker compose logs webhook-relay
```

---

## 4. GitHub side

The relay sends a `repository_dispatch` event with type `mlflow-model-version`. Your workflow needs to listen for it:

```yaml
# .github/workflows/ci.yml
on:
  repository_dispatch:
    types: [mlflow-model-version]

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - name: Print payload
        run: |
          echo "run_id : ${{ github.event.client_payload.data.run_id }}"
          echo "source : ${{ github.event.client_payload.data.source }}"
          echo "alias  : ${{ github.event.client_payload.data.alias }}"
```

The GitHub token (`GITHUB_TOKEN` in `.env`) needs the **`workflow`** scope.

---

## 5. Manage webhooks

| Action | Command |
|--------|---------|
| Create | `python webhook_relay/manage_webhooks.py create --url <url>` |
| List   | `python webhook_relay/manage_webhooks.py list` |
| Test   | `python webhook_relay/manage_webhooks.py test --id <id>` |
| Delete | `python webhook_relay/manage_webhooks.py delete --id <id>` |
