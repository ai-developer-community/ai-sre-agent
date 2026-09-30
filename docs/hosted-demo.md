# Hosted video demo

One shop and one investigator, both in `personal-infrastructure-505708`, region `europe-west2`. Client projects are not connected. The model investigates through four fixed read tools. The console also supports an explicitly approved, fixed-target rollback through a separate executor path. See [approved recovery](approved-recovery.md) for the recording flow and access boundaries.

## Topology

Cloud Monitoring sends shop alarms to the `sre-demo-alerts` Pub/Sub topic. The `sre-demo-console` Cloud Run service pulls notifications, persists them in Cloud SQL PostgreSQL, and runs one Claude investigation at a time. The React console is served by the same service. Minimum instances 1 and instance-based CPU allocation allow background work when no browser is open.

The console uses Google IAP for browser sign-in, with access granted to `owain@gradientwork.com`. Open the Cloud Run HTTPS URL directly. The demo shop remains private and uses IAM authentication. No client-side cloud keys are used. Closing the browser does not stop the cloud agent.

## Deploy

Authenticate the operator with gcloud, then run:

```sh
python scripts/cloud/demo.py setup
python scripts/cloud/demo.py deploy-healthy
python scripts/cloud/hosted.py infrastructure
python scripts/cloud/hosted.py deploy --model claude-opus-5-5
python scripts/cloud/hosted.py proxy
```

Enable the chosen Claude model in Vertex Model Garden for this project first. The model ID above is supported by the provider but still requires access in this project. A deployment without `--model` starts the console and queues incoming alerts with the model worker paused, displaying the configuration gap; it is not a successful agent rehearsal. Use `--vertex-region` when the enabled model needs a different model location.

The infrastructure command creates a small PostgreSQL 17 instance (`sre-demo-db`, `db-f1-micro`, 10 GB initial storage, daily backup), an application database/user and a database URL in Secret Manager. Database credentials are generated and transmitted without printing them or writing them to the repository. The runtime uses Cloud Run's Cloud SQL socket and its attached service account. It needs no local ADC credentials.

Source deployment uses a separate `sre-demo-builder` identity with read access to the source bucket, write access to the image repository and build logging permission. The investigator has telemetry reads, model invocation, access to its database secret, Cloud SQL connectivity and subscriber access on the demo subscription. The shop has no project roles. No keys are created.

## Record

Open `http://localhost:8080` after starting the proxy. Use the shop URL printed by `deploy-healthy` or saved in ignored `.demo-state`:

```sh
python scripts/load.py SHOP_URL --authenticated --rps 5
python scripts/cloud/demo.py deploy-broken
```

`SHOP_URL` means the deployed URL, not a local fixture. Load runs until Ctrl-C, or for a bounded duration with `--seconds`. Tokens refresh during long runs. The script prints response codes and never token values. Only this fake shop checkout is called; no real payments occur.

Wait for the real Monitoring notification and inspect the resulting investigation. Ask what changed and whether an alternative explanation fits. The configured alarm threshold is over 0.2 server errors per second for 60 seconds; metric ingestion and notification delivery add delay.

Run `python scripts/cloud/demo.py rollback` and confirm its named healthy revision. Keep traffic running, then ask the agent to inspect fresh evidence. Close the incident only after verifying actual checkout recovery. A green liveness endpoint is not sufficient.

## Boundaries and failure handling

The queue and history survive restarts in Postgres. Duplicate Pub/Sub deliveries do not duplicate a run. Alerts must match the configured project, service and region. Standby revisions retry worker leadership during a rollout. Interrupted runs become visible failures requiring a human retry; queued work remains queued. A database-session loss during a model call can briefly overlap read-only work, so this is not an exactly-once distributed executor.

Keep one backend process and one Cloud Run instance for the demo. A rollout can briefly overlap old and new revisions; avoid deploying the console during a recorded investigation. The console has explicit host/origin allowlists and CSRF checks in addition to Cloud Run IAM. Tool responses are bounded and redact common secret fields, but this is not a general guarantee that arbitrary production logs are safe to publish. The demo contains no client data.

## Costs and shutdown

Cloud SQL and the minimum Cloud Run instance incur ongoing charges even when the browser is closed. Model calls, builds, storage and requests add usage charges. Each model investigation has a two-dollar SDK budget and a four-minute timeout; these are per-run limits, not a project spending cap.

Stop load and the local proxy after recording. To pause the investigator, deploy with `SUBSCRIBER_ENABLED=false` and scale its minimum instances to zero; Pub/Sub retains undelivered messages for one day. Do not pause by deleting the database. Deliberate cloud teardown must remove the named demo resources only, and should happen after saving any recording evidence you want to keep. Nothing automatically deletes infrastructure or incident history.
