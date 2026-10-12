"""
CLI pour gérer les webhooks sur une instance MLflow.

Usage:
    python webhook_relay/manage_webhooks.py create --url https://ton-endpoint.com/webhook
    python webhook_relay/manage_webhooks.py list
    python webhook_relay/manage_webhooks.py test --id <webhook_id>
    python webhook_relay/manage_webhooks.py delete --id <webhook_id>
"""

import argparse
import os
import secrets
import sys

import mlflow
from mlflow.tracking import MlflowClient

# The event that fires when promote.py (or the MLflow UI) sets @champion
TRIGGER_EVENT = "model_version_alias.created"


def _setup_mlflow() -> MlflowClient:
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
    username = os.environ.get("MLFLOW_TRACKING_USERNAME")
    password = os.environ.get("MLFLOW_TRACKING_PASSWORD")

    if username and password:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(tracking_uri)
        netloc = f"{username}:{password}@{parsed.netloc}"
        tracking_uri = urlunparse(parsed._replace(netloc=netloc))

    mlflow.set_tracking_uri(tracking_uri)
    return MlflowClient()


def cmd_create(args) -> None:
    client = _setup_mlflow()

    # Generate a random secret if none provided
    # Save this secret — you will need it in your endpoint to verify the signature
    webhook_secret = args.secret or secrets.token_hex(32)
    if not args.secret:
        print(f"Generated secret : {webhook_secret}")
        print("⚠️  Save this secret — set it in your endpoint as MLFLOW_WEBHOOK_SECRET")
        print()

    webhook = client.create_webhook(
        name=args.name,
        url=args.url,
        events=[TRIGGER_EVENT],
        description=(
            "Fires when @champion alias is set. "
            "The receiving endpoint should call GitHub repository_dispatch."
        ),
        secret=webhook_secret,
    )

    print(f"✅ Webhook created")
    print(f"   ID     : {webhook.webhook_id}")
    print(f"   Name   : {webhook.name}")
    print(f"   URL    : {webhook.url}")
    print(f"   Event  : {TRIGGER_EVENT}")
    print(f"   Status : {webhook.status}")


def cmd_list(args) -> None:
    client = _setup_mlflow()
    webhooks = client.list_webhooks()

    if not webhooks:
        print("No webhooks registered.")
        return

    for wh in webhooks:
        print(f"ID     : {wh.webhook_id}")
        print(f"Name   : {wh.name}")
        print(f"URL    : {wh.url}")
        print(f"Events : {', '.join(wh.events)}")
        print(f"Status : {wh.status}")
        print()


def cmd_test(args) -> None:
    client = _setup_mlflow()
    result = client.test_webhook(args.id, event=TRIGGER_EVENT)

    if result.success:
        print(f"✅ Webhook test successful (HTTP {result.response_status})")
    else:
        print(f"❌ Webhook test failed (HTTP {result.response_status})")
        if result.error_message:
            print(f"   Error: {result.error_message}")


def cmd_delete(args) -> None:
    client = _setup_mlflow()
    client.delete_webhook(args.id)
    print(f"✅ Webhook {args.id} deleted")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage MLflow webhooks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # create
    p_create = sub.add_parser("create", help="Register a new webhook")
    p_create.add_argument("--url",    required=True, help="Endpoint URL that will receive the webhook")
    p_create.add_argument("--name",   default="champion-ci-trigger", help="Webhook name")
    p_create.add_argument("--secret", default=None,
                          help="HMAC secret (auto-generated if omitted)")

    # list
    sub.add_parser("list", help="List all registered webhooks")

    # test
    p_test = sub.add_parser("test", help="Send a test payload to a webhook")
    p_test.add_argument("--id", required=True, help="Webhook ID")

    # delete
    p_delete = sub.add_parser("delete", help="Delete a webhook")
    p_delete.add_argument("--id", required=True, help="Webhook ID")

    args = parser.parse_args()

    dispatch = {
        "create": cmd_create,
        "list":   cmd_list,
        "test":   cmd_test,
        "delete": cmd_delete,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
