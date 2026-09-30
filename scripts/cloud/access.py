"""Explicit, demo-only access changes for browser sign-in and approved recovery."""

import argparse

from demo import PROJECT, REGION, gcloud
from demo import SERVICE as SHOP
from hosted import ACCOUNT
from hosted import SERVICE as CONSOLE


def browser_access(user):
    if not user or "@" not in user:
        raise SystemExit("Supply the approved operator email with --user")
    gcloud("services", "enable", "iap.googleapis.com", "cloudresourcemanager.googleapis.com")
    gcloud("beta", "services", "identity", "create", "--service", "iap.googleapis.com")
    number = gcloud("projects", "describe", PROJECT, "--format=value(projectNumber)")
    gcloud(
        "run",
        "services",
        "add-iam-policy-binding",
        CONSOLE,
        "--region",
        REGION,
        "--member",
        f"serviceAccount:service-{number}@gcp-sa-iap.iam.gserviceaccount.com",
        "--role",
        "roles/run.invoker",
    )
    gcloud("beta", "run", "services", "update", CONSOLE, "--region", REGION, "--iap")
    gcloud(
        "beta",
        "iap",
        "web",
        "add-iam-policy-binding",
        "--resource-type=cloud-run",
        "--service",
        CONSOLE,
        "--region",
        REGION,
        "--member",
        f"user:{user}",
        "--role",
        "roles/iap.httpsResourceAccessor",
    )
    print("Google sign-in enabled for the named operator. No public access granted.")


def rollback_access():
    role_id = "sreDemoTrafficRollback"
    roles = gcloud("iam", "roles", "list", json_output=True)
    role_name = f"projects/{PROJECT}/roles/{role_id}"
    existing = next((r for r in roles if r["name"] == role_name), None)
    permissions = {"run.services.get", "run.services.update"}
    if existing:
        role = gcloud("iam", "roles", "describe", role_id, json_output=True)
        if set(role.get("includedPermissions", [])) != permissions:
            raise SystemExit(
                "Existing rollback role has unexpected permissions; refusing to change it"
            )
    else:
        gcloud(
            "iam",
            "roles",
            "create",
            role_id,
            "--title",
            "Demo traffic rollback",
            "--permissions",
            ",".join(sorted(permissions)),
            "--stage=GA",
        )
    for role in (role_name, "roles/run.invoker"):
        gcloud(
            "run",
            "services",
            "add-iam-policy-binding",
            SHOP,
            "--region",
            REGION,
            "--member",
            f"serviceAccount:{ACCOUNT}",
            "--role",
            role,
        )
    print("Demo runtime may update only the shop service and invoke its checkout.")
    print("IAM update permission covers the service; application code limits updates to traffic.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["browser", "rollback"])
    parser.add_argument("--user", default="")
    args = parser.parse_args()
    if args.action == "browser":
        browser_access(args.user)
    else:
        rollback_access()


if __name__ == "__main__":
    main()
