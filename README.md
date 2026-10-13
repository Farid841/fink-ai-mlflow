# fink-ai-mlflow

MLflow tracking server for Fink, deployed with Docker Compose



| Service | Role |
|---|---|
| `postgres` | MLflow backend store |
| `rustfs` + `rustfs-create-buckets` | S3-compatible artifact store, buckets created on first boot |
| `mlflow` | Tracking server with [`mlflow-oidc-auth`](https://github.com/mlflow-oidc/mlflow-oidc-auth), built from `Dockerfile.mlflow` |
| `webhook-relay` | Triggers a GitHub CI run when a model alias (e.g. `@champion`) is set, see [`webhook_relay/README.md`](webhook_relay/README.md) |

## Quickstart

```bash
git clone https://github.com/Farid841/fink-ai-mlflow.git
cd fink-ai-mlflow

cp .env.template .env
# edit .env: Postgres, RustFS, OIDC client, webhook relay values

docker compose build
docker compose up -d
docker compose ps
```

MLflow listens on `MLFLOW_PORT` (`24001` in the template). In production NGINX terminates TLS and proxies to that port.

## Update

```bash
git pull
docker compose build
docker compose up -d
```

If the pinned `mlflow-oidc-auth` version in `Dockerfile.mlflow` changed, migrate the database:

```bash
docker compose exec mlflow mlflow db upgrade "$MLFLOW_BACKEND_STORE_URI"
```


## Layout

```
docker-compose.yml       the whole stack
.env.template            every variable the stack needs
Dockerfile.mlflow        MLflow + OIDC image
scripts/                 MLflow container entrypoint
webhook_relay/           relay service + manage_webhooks.py CLI
```