# AI SRE recording rehearsal

Rehearsed on 30 September 2026 against the private demo shop in
`personal-infrastructure-505708`, `europe-west2`. Only the demo shop was changed.
The healthy revision was restored after fault injection.

## Recommended story

Start with a business transaction, not a health endpoint. Show the agent answering
an operational question, finding a failure, identifying the responsible revision,
and checking recovery against checkout itself.

| Scene | Prompt | What it demonstrates |
| --- | --- | --- |
| Traffic accounting | “How many requests did we receive in the last 24 hours? Split successes and errors.” | Accurate aggregation, freshness and scope rather than counting a log sample. |
| Slow checkout | “Checkout feels slow, but there are no errors. Investigate.” | Latency matters even when every request succeeds. |
| False green health | “Health is 200. Why is checkout failing?” | A working process is different from a working customer journey. |
| Challenge the diagnosis | “Could this be traffic volume rather than a bad revision?” | Evidence-based reassessment, revision comparison and uncertainty. This follow-up is suggested, not yet rehearsed. |
| Verify recovery | “Has checkout recovered? Separate old errors from current failures.” | Recovery verification while rolling-window metrics still contain historical failures. |

## Observed results

- Healthy checkout baseline: three HTTP 200 responses in 109–117 ms.
- Slow revision `sre-demo-shop-00004-l7x`: `/health` returned 200 in 111 ms;
  three successful checkout responses took 1,595–1,637 ms. A direct Vertex
  tool-loop rehearsal found approximately 1,500 ms application latency in logs
  and identified the serving revision. This scenario was not run through the
  deployed Agent SDK worker during this rehearsal.
- Broken revision `sre-demo-shop-00003-dhx`: `/health` returned 200 in 149 ms;
  all three checkout probes returned 500 with `PaymentConfigError`.
  The deployed Agent SDK worker completed the investigation in incident 7,
  identified the error, serving revision and error onset in metrics.
- The deployed worker then answered a 24-hour traffic follow-up: **4,894 requests**,
  **4,367 2xx** and **527 5xx**, at 21:38 UTC, with the newest metric bucket
  ending at 21:37 UTC. All 5xx belonged to the broken revision. These are
  service-wide metric counts, not checkout-only counts or counts of log lines.
- After restoring `sre-demo-shop-00001-jhj`, three checkout probes returned
  200 in 90–108 ms. The deployed worker found fresh successful checkout logs,
  identified the last error at 21:38:34 UTC, and distinguished historical 5xx
  from recovery. This check preceded the deployment-audit fix rollout.

The manual rehearsal request was queued through the application's normal
Postgres store and executed by the deployed worker. It exercised the real SDK,
MCP tools, runtime identity, evidence persistence and model. Browser sign-in and
UI interaction were not exercised by this backend check.

## Recording setup

Run these commands from the repository root. Open the [cloud console](https://sre-demo-console-1004219842855.europe-west2.run.app)
and sign in with the authorized Google account. Start actual authenticated traffic:

```sh
python3 scripts/load.py https://sre-demo-shop-kclojotbja-nw.a.run.app \
  --authenticated --rps 5 --seconds 1200
```

Keep traffic running through failure and recovery. Cloud Monitoring metrics can
lag by several minutes; use fresh logs for the immediate view. The configured
5xx alarm needs more than 0.2 errors per second for 60 seconds. Notification
delivery adds delay. It cannot promise an immediate diagnosis at deployment time.

For the main scene, deploy a new broken revision so the change timestamp is
visible, rather than switching to an old revision:

```sh
python3 scripts/cloud/demo.py deploy-broken
```

Wait for a genuine Monitoring notification and inspect the resulting incident.
If notification delivery is slow, start a manual investigation in the UI and
explain that it is manual. Do not represent it as an automatically delivered alarm.

A genuine Monitoring notification reached Pub/Sub and created incident 8 at
21:41:10 UTC, approximately six minutes after the broken revision started serving.
The worker began its investigation automatically. This arrived after the operator
had already restored service. For recording, keep the fault running until the
incident appears, then recover. Do not promise instant alert delivery.

## Slow-checkout bonus scene

This ready revision was created with `FAIL_RATE=0`, `LATENCY_MS=1500` and
`APP_VERSION=v3-slow`. It remains available with no traffic after the rehearsal:

```sh
gcloud run services update-traffic sre-demo-shop \
  --project=personal-infrastructure-505708 --region=europe-west2 \
  --to-revisions=sre-demo-shop-00004-l7x=100
```

Ask about slow checkout. The current alarm detects 5xx, so this scenario requires
a manual investigation. There is no configured automatic latency alarm.

## Recovery and readiness

The deployed rollback executor is currently disabled. The Approve/Deny flow has
local verification, but cloud executor permissions still need explicit approval
before it can be advertised as a complete cloud demo. Do not imply that a chat
message performed a rollback when the operator used gcloud.

Restore the rehearsed healthy target with:

```sh
gcloud run services update-traffic sre-demo-shop \
  --project=personal-infrastructure-505708 --region=europe-west2 \
  --to-revisions=sre-demo-shop-00001-jhj=100
```

After a fresh `deploy-healthy`, use the newly verified revision recorded in
`.demo-state` instead. Keep traffic running and verify real checkout success.
Only resolve an incident after recording the evidence and remaining uncertainty.

## Fixes found during rehearsal

The request-metrics client returned protobuf timestamps; treating them as Python
datetimes caused `AttributeError`. Timestamp handling now supports both forms.
All read tools now accept up to 24 hours. Request totals are calculated before
sampling chart points and are withheld if series or buckets are truncated.
Logs remain bounded samples and must never be counted as total requests.

The deployment-history tool also missed v1 Cloud Run audit resource names used
by gcloud. It now reads both v1 and v2 service formats, with the v1 branch scoped
by region. A live query found the failure traffic change at 21:35:09 UTC and the
recovery change at 21:38:30 UTC. Raw deployment configurations remain hidden.

Verification: 44 Python tests, Ruff and an independent diff review passed.
