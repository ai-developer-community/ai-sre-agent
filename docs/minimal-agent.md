> Historical hosted design sketch. Current v1 runs locally; see [ARCHITECTURE.md](../ARCHITECTURE.md) and [README.md](../README.md).

# Minimal Claude agent on GCP

> Design sketch, not deployed code. The behavior and acceptance criteria live in [ARCHITECTURE.md](../ARCHITECTURE.md).

## Smallest useful service

Use Python 3.12, FastAPI and the Claude Agent SDK in one Cloud Run container. FastAPI serves the built web UI, chat routes and Pub/Sub handler. Cloud SQL PostgreSQL stores application state. Each request runs the SDK to completion within a bounded time; do not launch untracked work after returning HTTP 200.

There are three entry points into the same agent runner:

| Entry | Context supplied by backend | Permitted outcome |
|---|---|---|
| Monitoring alert | Validated alert, service context and incident history | Investigate and propose rollback |
| User question | User message, recent conversation and latest evidence | Query fresh data and answer |
| User-authorized rollback | Persisted authorization for one proposal | Execute that proposal and check recovery |

Keep the run loop simple: assemble context, create tools bound to the run, configure the SDK, consume messages, persist progress and final output. Store application history explicitly rather than relying on the SDK's local session files.

## Authentication

**Supported in documentation:** Claude's runtime supports Google Application Default Credentials (ADC). Configure these server-side variables:

```bash
CLAUDE_CODE_USE_VERTEX=1
ANTHROPIC_VERTEX_PROJECT_ID=personal-infrastructure-505708
CLOUD_ML_REGION=global
```

Set `CLAUDE_MODEL` to an exact model ID confirmed available in this project and location. The model region is independent of the Cloud Run region. Google model enablement, billing and quota are prerequisites; `gcloud auth login` alone does not establish them. See [Anthropic's Google setup](https://code.claude.com/docs/en/google-vertex-ai).

Locally, ADC is configured separately with `gcloud auth application-default login`. On Cloud Run, attach `sre-agent-sa`; the runtime discovers short-lived credentials through Google's metadata service. Do not upload a service-account key or set `GOOGLE_APPLICATION_CREDENTIALS` on the Cloud Run service. See [Cloud Run service identity](https://docs.cloud.google.com/run/docs/securing/service-identity).

The three authentication paths are distinct:

| Connection | Identity and authority |
|---|---|
| Agent to model and read APIs | `sre-agent-sa`: model prediction, Logging viewer, Monitoring viewer, Run viewer, MCP tool invocation if using remote MCP, and application database access |
| Backend rollback tool to Cloud Run | Explicit impersonation of `shop-rollback-sa`; token creation permission only on this identity; traffic-update permissions only for the shop |
| User or Pub/Sub to backend | Operator's Google identity through the local proxy, or the dedicated Pub/Sub invoker's OIDC token; enforce route-specific access in the app |

Database access is a write permission for application memory, not infrastructure mitigation authority. Prefer a custom model-invocation role with `aiplatform.endpoints.predict` where feasible; verify all required permissions with smoke tests. Remote MCP servers require both MCP invocation permission and underlying read permissions. Do not grant Monitoring admin merely to make an MCP connection succeed.

If Vertex model access blocks the demo, use an Anthropic API key from Secret Manager. Explicitly switch provider settings and remove `CLAUDE_CODE_USE_VERTEX`; do not silently fall back or use a personal Claude login in the service.

## Small PostgreSQL database

Use a dedicated `sre_demo` database on a single-zone Cloud SQL PostgreSQL instance in `europe-west2`. Start with `db-f1-micro` and 10 GiB storage. Keep the connection pool at two connections with no overflow. The workload is a single agent plus lightweight UI reads.

The Python Connector authenticates using the runtime service account and automatic IAM database authentication. Use `pg8000`, SQLAlchemy and lazy refresh. This avoids storing a database password. Provision the IAM database user, Cloud SQL Client/Instance User roles and SQL schema privileges explicitly. Use a separate schema migration identity. Connect over the instance's public IP using the encrypted connector without adding public authorized networks. See [Google's connector guide](https://docs.cloud.google.com/sql/docs/postgres/connect-connectors).

Tables hold incidents, conversation messages, run status, action proposals, lessons and one lease row. Short transactions enforce deduplication and one-time authorization; close the transaction before any model or tool call. Local integration tests use real PostgreSQL, not SQLite, so transaction behavior matches deployment. See [the architecture's storage section](../ARCHITECTURE.md#postgresql-storage).

## Model-only smoke test

This is a complete minimal probe, to run after installing a pinned `claude-agent-sdk` release and setting the environment above plus the verified `CLAUDE_MODEL`. It exercises model authentication only, not Google tools or rollback. It incurs a model call. It has not been run for this project.

```python
import asyncio
import os

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query


async def main():
    options = ClaudeAgentOptions(
        model=os.environ["CLAUDE_MODEL"],
        system_prompt="Reply with exactly READY. Do not use tools.",
        tools=[],
        setting_sources=[],
        max_turns=1,
    )
    async with asyncio.timeout(60):
        async for message in query(prompt="Check model connectivity.", options=options):
            if isinstance(message, ResultMessage):
                if message.is_error or not message.result:
                    raise RuntimeError("Model smoke test failed")
                if message.result.strip() != "READY":
                    raise RuntimeError("Unexpected model smoke test response")
                print("Vertex model connectivity: READY")
                return
    raise RuntimeError("No final model result received")


asyncio.run(main())
```

The SDK Python package bundles the Claude runtime on supported platforms. Its current hosting guide says a separate Node installation is not required for the bundled native binary. Pin the release and test its Linux container, including timeout cleanup, before deployment. See [SDK hosting](https://code.claude.com/docs/en/agent-sdk/hosting).

## Tools for the actual agent

| Tool | Minimal contract |
|---|---|
| Logging read tools | Bounded queries for shop errors and deployment audit events; return real query links |
| Monitoring read tools | Error rate, request count and latency with explicit time windows and units |
| `get_shop_revisions` | Current traffic, exact revision names, timestamps and redacted config differences |
| `propose_rollback` | Validate a known healthy target and persist a concrete proposal; cannot authorize it |
| `rollback_shop` | Consume backend authorization, validate target and current traffic, execute once, persist result |
| `check_shop_health` | Probe checkout and inspect fresh post-action telemetry, with timestamps |

Use Google remote MCP for observability after verifying actual tool names and read-only access. Timebox connectivity work to 30 minutes; use Google client-library wrappers as the fallback. SDK custom tools can run in-process using `@tool` and `create_sdk_mcp_server`; no separate MCP hosting service is needed. The SDK documentation warns that `allowed_tools` grants automatic permission but does not limit available tools. Remove built-ins with `tools=[]`, use exact MCP names and deny unknown calls in a permission hook. See [Python SDK reference](https://code.claude.com/docs/en/agent-sdk/python).

Create a fresh in-process tool server per run. Bind run ID, conversation ID and persisted authorization in backend closures. Never accept an `authorized=true` argument from the model. A fresh OAuth token is obtained for each connection to a Google remote MCP server. The hooks log sanitized tool events; tool implementations independently enforce scope and authorization.

The trusted rollback wrapper can use an argument-list `gcloud` subprocess with explicit impersonation. Only that wrapper gets command execution. The SDK agent receives no Bash tool. Install the CLI in the image if this path is selected; alternatively use the Cloud Run client library with impersonated credentials. Pick and test one path before rehearsal.

## Deployment outline

Start with one warm Cloud Run instance, 2 GiB memory, one API process, a 600-second request timeout and HTTP concurrency 8. Permit only one agent run through a PostgreSQL lease row. HTTP concurrency must exceed one so polling works while triage is running. No background queue, bucket mount or standalone worker service is needed.

Open the private UI with:

```bash
gcloud run services proxy sre-agent \
  --project personal-infrastructure-505708 \
  --region europe-west2 \
  --port 8080
```

The proxy authenticates as the active Google account. This supports a private browser demo without a public login flow. Verify that forwarded identity headers support the application's operator-only session bootstrap. See [Cloud Run proxy](https://docs.cloud.google.com/sdk/gcloud/reference/run/services/proxy).

Build in this order: model-only smoke test, one real telemetry read, tool-backed diagnosis, authorized rollback and verification, then automatic alert delivery and UI polish. Rehearse two complete incidents before recording. This is an implementation order, not permission to claim the untested integrations work.

## Verified versus outstanding

Verified on 2026-09-29: the project exists, and the APIs for Vertex AI, Cloud Run, Pub/Sub, Logging, Monitoring, IAM Credentials and Cloud SQL Admin are enabled. Official documentation describes the SDK and Google authentication paths above.

Still unverified: exact model entitlement/region, runtime service-account permissions, MCP tool inventory, existing Cloud SQL instances and database login, private UI identity forwarding, container behavior, and live rollback. No resources, IAM bindings or model subscriptions were changed while writing this sketch.
