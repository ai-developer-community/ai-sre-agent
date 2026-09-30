#!/usr/bin/env python3
"""Explicit GCP demo setup. Nothing runs until a subcommand is selected."""

import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path

PROJECT = "personal-infrastructure-505708"
REGION = "europe-west2"
SERVICE = "sre-demo-shop"
TOPIC = "sre-demo-alerts"
SUBSCRIPTION = "sre-demo-agent"
ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".demo-state"


def gcloud(*args, json_output=False):
    command = ["gcloud", *args, "--project", PROJECT, "--quiet"]
    if json_output:
        command += ["--format=json"]
    for attempt in range(5):
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode == 0:
            break
        # Newly created Google service accounts can lag in IAM's binding validator.
        if (
            "add-iam-policy-binding" in args
            and "Service account" in result.stderr
            and "does not exist" in result.stderr
            and attempt < 4
        ):
            time.sleep(5 * (attempt + 1))
            continue
        print(result.stderr)
        result.check_returncode()
    return json.loads(result.stdout) if json_output else result.stdout.strip()


def build_identity():
    """Keep build rights separate from both deployed runtime identities."""
    bucket = f"run-sources-{PROJECT}-{REGION}"
    buckets = gcloud("storage", "buckets", "list", json_output=True)
    if not any(item.get("name") == bucket for item in buckets):
        gcloud(
            "storage",
            "buckets",
            "create",
            "gs://" + bucket,
            "--location",
            REGION,
            "--uniform-bucket-level-access",
            "--public-access-prevention",
        )
    repositories = gcloud(
        "artifacts", "repositories", "list", "--location", REGION, json_output=True
    )
    if not any(
        item["name"].rsplit("/", 1)[-1] == "cloud-run-source-deploy" for item in repositories
    ):
        gcloud(
            "artifacts",
            "repositories",
            "create",
            "cloud-run-source-deploy",
            "--location",
            REGION,
            "--repository-format=docker",
        )
    name = "sre-demo-builder"
    email = f"{name}@{PROJECT}.iam.gserviceaccount.com"
    accounts = gcloud("iam", "service-accounts", "list", json_output=True)
    if not any(account["email"] == email for account in accounts):
        gcloud("iam", "service-accounts", "create", name)
    member = "serviceAccount:" + email
    gcloud(
        "storage",
        "buckets",
        "add-iam-policy-binding",
        f"gs://run-sources-{PROJECT}-{REGION}",
        "--member",
        member,
        "--role=roles/storage.objectViewer",
    )
    gcloud(
        "artifacts",
        "repositories",
        "add-iam-policy-binding",
        "cloud-run-source-deploy",
        "--location",
        REGION,
        "--member",
        member,
        "--role=roles/artifactregistry.writer",
    )
    gcloud(
        "projects",
        "add-iam-policy-binding",
        PROJECT,
        "--member",
        member,
        "--role=roles/logging.logWriter",
        "--condition=None",
    )
    return f"projects/{PROJECT}/serviceAccounts/{email}"


def ensure_resource(list_args, create_args, resource_name):
    resources = gcloud(*list_args, json_output=True)
    if not any(item["name"].split("/")[-1] == resource_name for item in resources):
        gcloud(*create_args)


def monitoring(path, body=None, method=None):
    token = gcloud("auth", "print-access-token")
    request = urllib.request.Request(
        "https://monitoring.googleapis.com/v3/projects/" + PROJECT + "/" + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def monitoring_list(path):
    items = []
    page = path
    while True:
        result = monitoring(page)
        items.extend(result.get(path, []))
        if not result.get("nextPageToken"):
            return items
        from urllib.parse import urlencode

        page = path + "?" + urlencode({"pageToken": result["nextPageToken"]})


def setup():
    gcloud(
        "services",
        "enable",
        "run.googleapis.com",
        "cloudbuild.googleapis.com",
        "artifactregistry.googleapis.com",
        "logging.googleapis.com",
        "monitoring.googleapis.com",
        "pubsub.googleapis.com",
        "aiplatform.googleapis.com",
        "iamcredentials.googleapis.com",
    )
    ensure_resource(("pubsub", "topics", "list"), ("pubsub", "topics", "create", TOPIC), TOPIC)
    ensure_resource(
        ("pubsub", "subscriptions", "list"),
        (
            "pubsub",
            "subscriptions",
            "create",
            SUBSCRIPTION,
            "--topic",
            TOPIC,
            "--ack-deadline=60",
            "--message-retention-duration=1d",
        ),
        SUBSCRIPTION,
    )
    subscription = gcloud("pubsub", "subscriptions", "describe", SUBSCRIPTION, json_output=True)
    if subscription.get("topic") != f"projects/{PROJECT}/topics/{TOPIC}" or subscription.get(
        "pushConfig", {}
    ).get("pushEndpoint"):
        raise SystemExit("Existing demo subscription must be a pull subscription on the demo topic")
    accounts = gcloud("iam", "service-accounts", "list", json_output=True)
    for name in ("sre-demo-investigator", "sre-demo-shop"):
        email = f"{name}@{PROJECT}.iam.gserviceaccount.com"
        if not any(account["email"] == email for account in accounts):
            gcloud("iam", "service-accounts", "create", name)
    role_id = "sreDemoPredict"
    permissions = {"aiplatform.endpoints.predict", "serviceusage.services.use"}
    custom_roles = gcloud("iam", "roles", "list", "--show-deleted", json_output=True)
    existing_role = next(
        (role for role in custom_roles if role["name"].split("/")[-1] == role_id), None
    )
    if existing_role:
        if existing_role.get("deleted"):
            raise SystemExit("Demo predict role is deleted; restore it before setup")
        role = gcloud("iam", "roles", "describe", role_id, json_output=True)
        if set(role.get("includedPermissions", [])) != permissions:
            raise SystemExit("Existing demo predict role has unexpected permissions")
    else:
        gcloud(
            "iam",
            "roles",
            "create",
            role_id,
            "--title=SRE demo model prediction",
            "--stage=GA",
            "--permissions",
            ",".join(sorted(permissions)),
        )
    investigator = f"serviceAccount:sre-demo-investigator@{PROJECT}.iam.gserviceaccount.com"
    for role in (
        "roles/logging.viewer",
        "roles/monitoring.viewer",
        "roles/run.viewer",
        f"projects/{PROJECT}/roles/sreDemoPredict",
    ):
        gcloud(
            "projects",
            "add-iam-policy-binding",
            PROJECT,
            "--member",
            investigator,
            "--role",
            role,
            "--condition=None",
        )
    gcloud(
        "pubsub",
        "subscriptions",
        "add-iam-policy-binding",
        SUBSCRIPTION,
        "--member",
        investigator,
        "--role=roles/pubsub.subscriber",
    )
    channel_body = {
        "type": "pubsub",
        "displayName": "SRE demo alerts",
        "labels": {"topic": f"projects/{PROJECT}/topics/{TOPIC}"},
        "enabled": True,
    }
    channels = [
        channel
        for channel in monitoring_list("notificationChannels")
        if channel.get("displayName") == channel_body["displayName"]
    ]
    if len(channels) > 1:
        raise SystemExit(
            "Duplicate SRE demo notification channels; resolve in Monitoring before setup"
        )
    if channels:
        channel = channels[0]
        if (
            channel.get("type") != "pubsub"
            or channel.get("labels") != channel_body["labels"]
            or not channel.get("enabled", True)
        ):
            raise SystemExit(
                "Existing SRE demo channel differs from expected topic/type/enabled state"
            )
    else:
        channel = monitoring("notificationChannels", channel_body)
    number = gcloud("projects", "describe", PROJECT, "--format=value(projectNumber)")
    publisher = (
        f"serviceAccount:service-{number}@gcp-sa-monitoring-notification.iam.gserviceaccount.com"
    )
    gcloud(
        "pubsub",
        "topics",
        "add-iam-policy-binding",
        TOPIC,
        "--member",
        publisher,
        "--role=roles/pubsub.publisher",
    )
    policy = {
        "displayName": "SRE demo checkout 5xx",
        "combiner": "OR",
        "enabled": True,
        "notificationChannels": [channel["name"]],
        "conditions": [
            {
                "displayName": "Shop 5xx above 0.2/s for 60s",
                "conditionThreshold": {
                    "filter": (
                        'resource.type="cloud_run_revision" '
                        f'AND resource.labels.service_name="{SERVICE}" '
                        f'AND resource.labels.location="{REGION}" '
                        'AND metric.type="run.googleapis.com/request_count" '
                        'AND metric.labels.response_code_class="5xx"'
                    ),
                    "comparison": "COMPARISON_GT",
                    "thresholdValue": 0.2,
                    "duration": "60s",
                    "trigger": {"count": 1},
                    "aggregations": [
                        {
                            "alignmentPeriod": "60s",
                            "perSeriesAligner": "ALIGN_RATE",
                            "crossSeriesReducer": "REDUCE_SUM",
                            "groupByFields": [
                                "resource.labels.project_id",
                                "resource.labels.service_name",
                                "resource.labels.location",
                            ],
                        }
                    ],
                },
            }
        ],
        "documentation": {
            "mimeType": "text/markdown",
            "content": (
                "Demo shop checkout failures. Investigate recent revisions and "
                "PaymentConfigError logs. Human rollback only."
            ),
        },
    }
    policies = [
        item
        for item in monitoring_list("alertPolicies")
        if item.get("displayName") == policy["displayName"]
    ]
    if len(policies) > 1:
        raise SystemExit("Duplicate SRE demo policies; resolve before setup")
    if policies:
        policy["name"] = policies[0]["name"]
        monitoring("alertPolicies/" + policy["name"].split("/")[-1], policy, "PATCH")
    else:
        monitoring("alertPolicies", policy)
    print("Setup complete. Investigator has no Cloud Run mutation permission.")
    print(
        "Grant yourself serviceAccountTokenCreator on the investigator account "
        "if using impersonated ADC."
    )


def describe():
    return gcloud("run", "services", "describe", SERVICE, "--region", REGION, json_output=True)


def deployed_revision(service, broken):
    # When traffic is pinned, latestReady can still identify the old serving revision.
    revision = service["status"]["latestCreatedRevisionName"]
    detail = gcloud("run", "revisions", "describe", revision, "--region", REGION, json_output=True)
    containers = detail["spec"]["containers"]
    env = {item["name"]: item.get("value") for item in containers[0].get("env", [])}
    if (
        detail["metadata"]["labels"].get("serving.knative.dev/service") != SERVICE
        or env.get("APP_VERSION") != ("v2-broken" if broken else "v1-healthy")
        or env.get("FAIL_RATE") != ("1" if broken else "0")
    ):
        raise SystemExit("Created revision does not match the requested demo version")
    return revision


def deploy(broken=False):
    builder = build_identity()
    if broken:
        if not STATE.exists():
            raise SystemExit(
                "Run deploy-healthy first to record and verify a healthy rollback target"
            )
        previous = json.loads(STATE.read_text())
        if previous.get("project") != PROJECT or previous.get("service") != SERVICE:
            raise SystemExit("Saved demo state does not match this project/service")
        revision = gcloud(
            "run",
            "revisions",
            "describe",
            previous["healthy_revision"],
            "--region",
            REGION,
            json_output=True,
        )
        if (
            revision.get("metadata", {}).get("labels", {}).get("serving.knative.dev/service")
            != SERVICE
        ):
            raise SystemExit("Saved revision belongs to another service")
    gcloud(
        "run",
        "deploy",
        SERVICE,
        "--source",
        str(ROOT / "shop"),
        "--build-service-account",
        builder,
        "--region",
        REGION,
        "--service-account",
        f"sre-demo-shop@{PROJECT}.iam.gserviceaccount.com",
        "--no-allow-unauthenticated",
        "--invoker-iam-check",
        "--max=1",
        "--min=0",
        "--memory=256Mi",
        "--cpu=1",
        "--set-env-vars",
        "FAIL_RATE=1,LATENCY_MS=0,APP_VERSION=v2-broken"
        if broken
        else "FAIL_RATE=0,LATENCY_MS=0,APP_VERSION=v1-healthy",
    )
    # Explicitly move traffic after every take, even when a previous rollback pinned it.
    service = describe()
    revision = deployed_revision(service, broken)
    gcloud(
        "run",
        "services",
        "update-traffic",
        SERVICE,
        "--region",
        REGION,
        "--to-revisions",
        revision + "=100",
    )
    url = service["status"]["url"]
    if not broken:
        request = urllib.request.Request(
            url + "/checkout",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + gcloud("auth", "print-identity-token"),
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
            if result.get("status") != "paid" or result.get("version") != "v1-healthy":
                raise SystemExit("Healthy deployment checkout verification failed")
        STATE.write_text(
            json.dumps(
                {"project": PROJECT, "service": SERVICE, "healthy_revision": revision, "url": url},
                indent=2,
            )
            + "\n"
        )
    print(url)


def rollback():
    state = json.loads(STATE.read_text())
    if state.get("project") != PROJECT or state.get("service") != SERVICE:
        raise SystemExit("Saved demo state does not match project/service")
    revision = state["healthy_revision"]
    live_revision = gcloud(
        "run", "revisions", "describe", revision, "--region", REGION, json_output=True
    )
    if (
        live_revision.get("metadata", {}).get("labels", {}).get("serving.knative.dev/service")
        != SERVICE
    ):
        raise SystemExit("Saved revision belongs to another service")
    if input(f"Move {PROJECT}/{SERVICE} traffic to {revision}? Type rollback: ") != "rollback":
        raise SystemExit("Cancelled")
    gcloud(
        "run",
        "services",
        "update-traffic",
        SERVICE,
        "--region",
        REGION,
        "--to-revisions",
        revision + "=100",
    )
    print(
        "Traffic changed. Continue load and verify fresh checkout telemetry "
        "before claiming recovery."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["setup", "deploy-healthy", "deploy-broken", "rollback", "status"]
    )
    args = parser.parse_args()
    {
        "setup": setup,
        "deploy-healthy": deploy,
        "deploy-broken": lambda: deploy(True),
        "rollback": rollback,
        "status": lambda: print(json.dumps(describe(), indent=2)),
    }[args.action]()


if __name__ == "__main__":
    main()
