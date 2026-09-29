#!/usr/bin/env python3
"""Deploy the private, single-application video console. No client projects."""

import argparse
import json
import secrets
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

from demo import PROJECT, REGION, ROOT, build_identity, gcloud

INSTANCE = "sre-demo-db"
SERVICE = "sre-demo-console"
DATABASE = "sre_demo"
DB_USER = "sre_demo"
SECRET = "sre-demo-database-url"
ACCOUNT = f"sre-demo-investigator@{PROJECT}.iam.gserviceaccount.com"


def sql_api(path, body=None):
    token = gcloud("auth", "print-access-token")
    request = urllib.request.Request(
        f"https://sqladmin.googleapis.com/sql/v1beta4/projects/{PROJECT}/" + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def wait_operation(operation):
    deadline = time.monotonic() + 900
    while operation.get("status") != "DONE":
        if time.monotonic() > deadline:
            raise SystemExit("Cloud SQL operation still running; inspect status before rerunning")
        time.sleep(5)
        operation = sql_api("operations/" + operation["name"])
    if operation.get("error"):
        # Never print request bodies, database credentials or full API responses.
        raise SystemExit("Cloud SQL operation failed; inspect the operation in Cloud Console")


def infrastructure():
    gcloud("services", "enable", "sqladmin.googleapis.com", "secretmanager.googleapis.com")
    instances = gcloud("sql", "instances", "list", json_output=True)
    instance = next((item for item in instances if item["name"] == INSTANCE), None)
    if instance is None:
        gcloud(
            "beta",
            "sql",
            "instances",
            "create",
            INSTANCE,
            "--region",
            REGION,
            "--database-version=POSTGRES_17",
            "--edition=ENTERPRISE",
            "--tier=db-f1-micro",
            "--storage-size=10GB",
            "--storage-auto-increase",
            "--backup-start-time=03:00",
            "--labels=purpose=sre-demo",
        )
        instance = gcloud("sql", "instances", "describe", INSTANCE, json_output=True)
    if (
        instance.get("region") != REGION
        or instance.get("databaseVersion") != "POSTGRES_17"
        or instance.get("settings", {}).get("userLabels", {}).get("purpose") != "sre-demo"
    ):
        raise SystemExit("Existing database differs from the named demo configuration")
    if instance.get("state") != "RUNNABLE":
        raise SystemExit("Cloud SQL is still provisioning. Rerun infrastructure when RUNNABLE")
    if instance.get("settings", {}).get("ipConfiguration", {}).get("authorizedNetworks"):
        raise SystemExit("Demo database must not have direct authorized networks")

    databases = gcloud("sql", "databases", "list", "--instance", INSTANCE, json_output=True)
    if not any(item["name"] == DATABASE for item in databases):
        gcloud("sql", "databases", "create", DATABASE, "--instance", INSTANCE)

    existing = gcloud("secrets", "list", json_output=True)
    if any(item["name"].rsplit("/", 1)[-1] == SECRET for item in existing):
        url = gcloud("secrets", "versions", "access", "latest", "--secret", SECRET)
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "postgresql+psycopg"
            or parsed.username != DB_USER
            or parsed.path != "/" + DATABASE
            or urllib.parse.parse_qs(parsed.query).get("host")
            != [f"/cloudsql/{PROJECT}:{REGION}:{INSTANCE}"]
            or not parsed.password
        ):
            raise SystemExit("Existing demo database secret has an unexpected target")
        password = urllib.parse.unquote(parsed.password)
    else:
        users = gcloud("sql", "users", "list", "--instance", INSTANCE, json_output=True)
        if any(item["name"] == DB_USER for item in users):
            raise SystemExit("Database user already exists without its secret; refusing reset")
        password = secrets.token_urlsafe(36)
        host = urllib.parse.quote(f"/cloudsql/{PROJECT}:{REGION}:{INSTANCE}", safe="")
        url = f"postgresql+psycopg://{DB_USER}:{password}@/{DATABASE}?host={host}"
        # Secret bytes go over stdin, never command arguments, source files or stdout.
        subprocess.run(
            [
                "gcloud",
                "secrets",
                "create",
                SECRET,
                "--project",
                PROJECT,
                "--replication-policy=automatic",
                "--labels=purpose=sre-demo",
                "--data-file=-",
                "--quiet",
            ],
            input=url,
            text=True,
            check=True,
            stdout=subprocess.DEVNULL,
        )
    users = gcloud("sql", "users", "list", "--instance", INSTANCE, json_output=True)
    if not any(item["name"] == DB_USER for item in users):
        wait_operation(
            sql_api(f"instances/{INSTANCE}/users", {"name": DB_USER, "password": password})
        )
    gcloud(
        "projects",
        "add-iam-policy-binding",
        PROJECT,
        "--member=serviceAccount:" + ACCOUNT,
        "--role=roles/cloudsql.client",
        "--condition=None",
    )
    gcloud(
        "secrets",
        "add-iam-policy-binding",
        SECRET,
        "--member=serviceAccount:" + ACCOUNT,
        "--role=roles/secretmanager.secretAccessor",
    )
    print("Demo Postgres and database secret ready. No secret values printed.")


def deploy(model, vertex_region):
    builder = build_identity()
    number = gcloud("projects", "describe", PROJECT, "--format=value(projectNumber)")
    hostname = f"{SERVICE}-{number}.{REGION}.run.app"
    settings = {
        "PROJECT_ID": PROJECT,
        "REGION": REGION,
        "SHOP_SERVICE": "sre-demo-shop",
        "AGENT_PROVIDER": "vertex",
        "CLAUDE_MODEL": model,
        "VERTEX_REGION": vertex_region,
        "SUBSCRIBER_ENABLED": "true",
        "PUBSUB_SUBSCRIPTION": "sre-demo-agent",
        "ALLOWED_HOSTS": json.dumps([hostname, "localhost", "127.0.0.1"]),
        "ALLOWED_ORIGINS": json.dumps(
            [f"https://{hostname}", "http://localhost:8080", "http://127.0.0.1:8080"]
        ),
    }
    # JSON is valid YAML and keeps array-valued environment variables intact.
    with tempfile.TemporaryDirectory(prefix="sre-demo-deploy-") as directory:
        env_file = Path(directory) / "env.json"
        env_file.write_text(json.dumps(settings))
        gcloud(
            "run",
            "deploy",
            SERVICE,
            "--source",
            str(ROOT),
            "--region",
            REGION,
            "--build-service-account",
            builder,
            "--service-account",
            ACCOUNT,
            "--no-allow-unauthenticated",
            "--invoker-iam-check",
            "--min=1",
            "--max=1",
            "--cpu=1",
            "--memory=1Gi",
            "--no-cpu-throttling",
            "--timeout=300",
            "--concurrency=20",
            "--add-cloudsql-instances",
            f"{PROJECT}:{REGION}:{INSTANCE}",
            "--set-secrets",
            f"DATABASE_URL={SECRET}:latest",
            "--env-vars-file",
            str(env_file),
        )
    service = gcloud("run", "services", "describe", SERVICE, "--region", REGION, json_output=True)
    # gcloud proxy targets status.url, which can be the legacy hashed service URL.
    actual_url = service["status"]["url"]
    actual_host = urllib.parse.urlsplit(actual_url).hostname
    if actual_host and actual_host != hostname:
        hosts = json.loads(settings["ALLOWED_HOSTS"]) + [actual_host]
        origins = json.loads(settings["ALLOWED_ORIGINS"]) + [actual_url]
        gcloud(
            "run",
            "services",
            "update",
            SERVICE,
            "--region",
            REGION,
            "--update-env-vars",
            "^|^ALLOWED_HOSTS=" + json.dumps(hosts) + "|ALLOWED_ORIGINS=" + json.dumps(origins),
        )
    # IAM authentication remains required. Fail closed if an existing service was public.
    policy = gcloud(
        "run", "services", "get-iam-policy", SERVICE, "--region", REGION, json_output=True
    )
    for binding in policy.get("bindings", []):
        if binding.get("role") == "roles/run.invoker":
            for member in ("allUsers", "allAuthenticatedUsers"):
                if member in binding.get("members", []):
                    gcloud(
                        "run",
                        "services",
                        "remove-iam-policy-binding",
                        SERVICE,
                        "--region",
                        REGION,
                        "--member",
                        member,
                        "--role=roles/run.invoker",
                    )
    print(f"Private console: https://{hostname}")
    print("Use the proxy action to open the cloud console on localhost:8080.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["infrastructure", "deploy", "proxy", "status"])
    parser.add_argument("--model", default="", help="Exact enabled Vertex model ID")
    parser.add_argument("--vertex-region", default="global")
    args = parser.parse_args()
    if args.action == "infrastructure":
        infrastructure()
    elif args.action == "deploy":
        deploy(args.model, args.vertex_region)
    elif args.action == "proxy":
        subprocess.run(
            [
                "gcloud",
                "run",
                "services",
                "proxy",
                SERVICE,
                "--project",
                PROJECT,
                "--region",
                REGION,
                "--port=8080",
            ],
            check=True,
        )
    else:
        print(
            gcloud(
                "run",
                "services",
                "describe",
                SERVICE,
                "--region",
                REGION,
                "--format=table(status.url,status.latestReadyRevisionName)",
            )
        )
        print("Use Cloud Console to inspect the service and SQL state.")


if __name__ == "__main__":
    main()
