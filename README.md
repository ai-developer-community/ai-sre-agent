# On-call desk

A minimal Claude agent investigates a real Cloud Run shop. Cloud Monitoring detects failures, Pub/Sub delivers alerts, and the agent reads logs, request metrics and deployment history. A web console shows its evidence and lets you challenge the diagnosis. PostgreSQL retains incidents and chat across restarts.

**The agent investigates; the operator approves recovery.** An optional deterministic rollback executor prepares a saved revision change, requires an explicit Approve decision, and closes the incident only after five successful checkout checks. It is disabled until a healthy revision and demo-scoped permissions are configured. See [approved recovery](docs/approved-recovery.md). Chat can also schedule a persistent deployment watch. See [deployment monitoring](docs/deployment-watch.md). There is no autonomous rollback, Slack integration or alert correlation.

## Hosted video version

Follow [hosted deployment and recording](docs/hosted-demo.md). Cloud Run hosts the agent and console; Cloud SQL stores incidents. The cloud agent runs independently of your laptop. Open the [IAP-protected console](https://sre-demo-console-1004219842855.europe-west2.run.app) and sign in with the authorized Google account. The shop uses IAM authentication. Only the demo app is monitored; no client projects are connected.

## Run locally

Requires Python 3.12+, uv, Node 20+, Docker and gcloud. From this directory:

```bash
uv sync --frozen
npm ci --prefix frontend
npm run build --prefix frontend
docker compose up -d --wait
cp .env.example .env
uv run uvicorn sre_agent.main:app --host 127.0.0.1 --port 8000
```

Open [localhost:8000](http://localhost:8000). An unset model displays a configuration gap and leaves work queued until a model is configured. PostgreSQL listens only on localhost:55432; its published password is for the local demo container only. Keep the backend on localhost and use one worker process, without auto-reload during recording.

## Connect Claude and Google Cloud

The runtime uses Application Default Credentials, which are separate from your CLI login. The agent only exposes four read tools; infrastructure mutation tools and the SDK's built-in shell/file tools are disabled. For least privilege, use the investigator identity created by setup rather than personal owner credentials.

1. Follow [cloud setup](scripts/cloud/README.md) to create demo-only accounts, alerting and the shop in `personal-infrastructure-505708`.
2. Grant your operator account Token Creator on the investigator service account, then configure impersonated ADC as described there. This is limited to that service account, not the whole project.
3. Enable an available Claude model in Vertex Model Garden. Set its exact ID as `CLAUDE_MODEL` in `.env`; set `VERTEX_REGION` to a supported model location. Do not assume the shop region is a model region.
4. Set `SUBSCRIBER_ENABLED=true` after the pull subscription exists. Restart the backend after changing `.env`.
5. Run `uv run python -m sre_agent.doctor` to test configuration, ADC, read access and the model without changing infrastructure.

For the explicit Anthropic API alternative set `AGENT_PROVIDER=anthropic`, `ANTHROPIC_API_KEY` and an API model ID in `.env`. Google ADC is still required for telemetry. The runtime does not use your personal Claude CLI login. Never commit `.env`, credentials, captured production logs or private incident records.

SDK tools use Google client libraries inside an in-process MCP server. This avoids deploying another server or depending on a hosted MCP endpoint. Tool names and resource filters are fixed to the configured shop. Every tool result is bounded and saved as evidence. Logs Explorer links include the query and window; Metrics Explorer links open the explorer and the evidence includes the filter/window to reproduce.

## Record the demo

1. Deploy healthy and start `python scripts/load.py SHOP_URL --authenticated --rps 5`. Give the charts ten minutes of baseline.
2. Open the console and ask “How is production doing?” Check actual timestamps and evidence.
3. Run `python scripts/cloud/demo.py deploy-broken`. This sends traffic explicitly to a revision with checkout failures.
4. Wait for the real alert. The agent investigates automatically while the hosted worker is running. An alternative is **New investigation**, asking it to investigate checkout errors against the same live data.
5. Open evidence and ask “Could this be something other than the deployment?” The agent should test that hypothesis, not agree automatically.
6. With approved recovery configured, send “rollback the change”, review the exact revision card and choose **Approve** or **Deny**. Approval runs checkout checks before resolving the incident. Without recovery configured, use the manual rollback script and ask the agent to re-check production.
7. For a manual fix, close with your resolution notes after checking health.
8. Deploy broken again for the next take. Existing conversations and lessons remain in Postgres.

While offline, Pub/Sub retains messages for the configured retention window. After local persistence, notifications are acknowledged and queued work survives restart. Only one investigator runs at a time. Caught model failures are visible and require a human retry; an interrupted run is marked failed on restart. Closed source incidents stay closed when late notifications arrive. Different Monitoring incidents remain separate; no correlation is attempted.

## Checks

```bash
docker compose up -d --wait
uv run pytest -q
uv run ruff check sre_agent tests shop scripts
npm run build --prefix frontend
```

Database tests create and drop uniquely named test schemas in the local database. Test doubles exercise error paths and SDK permissions; they are not evidence of live model accuracy. See [verification](docs/verification.md) for actual results and gaps.

## Video and reference material

[Full video outline and diagrams](docs/video-outline.md) covers the story, recording sequence and claims. [Insights from the on-call kit](docs/oncall-kit-insights.md) maps the reference's ideas to this implementation and gives a short demonstration outline. [Architecture](ARCHITECTURE.md) describes the code as built. This is an independent demo inspired by the kit, not an installation of its Slack workflow.

The kit is a reference implementation. Its lessons about evidence, explicit uncertainty and human ownership transfer well; a controlled shop failure is not a production-readiness evaluation.

## Stop and clean up

Stop the backend and load generator with Ctrl-C. `docker compose down` stops local Postgres and keeps its data. Do not add `-v` unless you intend to erase all local incidents and lessons. Cloud resources remain until you deliberately remove them; the deploy script uses min instances 0 to avoid idle shop instances. Cloud storage, builds and traffic can still incur costs. No cleanup script deletes unrelated project resources.
