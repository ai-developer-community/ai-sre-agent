# Live demo runbook

Run commands from `~/Code/github/owainlewis/ai-sre-agent`. Open the [cloud console](https://sre-demo-console-1004219842855.europe-west2.run.app) and finish Google sign-in before recording. This operates only the fake shop in `personal-infrastructure-505708`.

## Baseline

Preparation on 1 October closed six completed investigations with operator notes, preserved their history, and deployed healthy revision `sre-demo-shop-00005-xkj`. Three checkout probes returned paid orders with that revision. The agent has permission to invoke this private shop. `.demo-state` holds the verified recovery target.

The cloud watcher then made six verified successful checkout probes and Claude completed a fresh baseline investigation. The one-minute watch was inconclusive while metrics were still arriving. A later check found 291 requests, all 2xx on the healthy revision, with the latest sample at 12:05 UTC. Both preparation records were closed, leaving zero open investigations at 12:06 UTC. These are preparation observations, not a permanent health guarantee.

A 30-minute traffic run at three requests per second was started during preparation. If it has ended, run this in a separate terminal:

```sh
python3 scripts/load.py https://sre-demo-shop-kclojotbja-nw.a.run.app --authenticated --rps 3 --seconds 1800
```

Keep this traffic running through failure and recovery. Requests make fake orders, not real payments. Before each scenario, restore the healthy revision, stop any existing watch, finish any investigation, and resolve its record with a truthful note.

## 1. A healthy process with broken checkout

Say: “The process can be alive while customers cannot check out. Let's deploy a payment regression and let the agent investigate.”

Start a new conversation:

> Watch the next deployment for five minutes. Check checkout success, errors and latency. Investigate any regression and ask me before rolling back.

Wait for the UI to confirm the watch is waiting. Then deploy a new revision using the existing image, so there is no source build during the recording:

```sh
gcloud run services update sre-demo-shop \
  --project=personal-infrastructure-505708 --region=europe-west2 \
  --update-env-vars=FAIL_RATE=1,LATENCY_MS=0,APP_VERSION=v2-broken \
  --no-traffic --quiet
gcloud run services update-traffic sre-demo-shop \
  --project=personal-infrastructure-505708 --region=europe-west2 \
  --to-latest --quiet
```

Expected: checkout returns 500 with `PaymentConfigError`, while `/health` stays 200. The watch detects three consecutive verified failures and queues an investigation. Show the watch observations, investigation, evidence links, and revision comparison.

To show liveness without printing your token, run this authenticated probe:

```sh
python3 - <<'PY'
import json
import subprocess
from urllib.request import Request, urlopen

token = subprocess.check_output(
    ['gcloud', 'auth', 'print-identity-token'], text=True
).strip()
request = Request(
    'https://sre-demo-shop-kclojotbja-nw.a.run.app/health',
    headers={'Authorization': 'Bearer ' + token},
)
with urlopen(request, timeout=15) as response:
    print(response.status, json.load(response))
PY
```

Ask:

> What changed? Show the evidence linking the failure to the serving revision. Could this be a dependency outage instead?

The regular Monitoring alarm also arrives through Pub/Sub. Its threshold is over 0.2 server errors per second for 60 seconds, with additional ingestion and notification delay. It can create a separate incident from the watch. Wait for the real notification when showing the alert path; do not describe a chat-triggered investigation as an alert.

## 2. HTTP 200, but checkout is too slow

Restore the baseline using the recovery command below. Start a new conversation with the same watch prompt and wait for confirmation. Then run:

```sh
gcloud run services update sre-demo-shop \
  --project=personal-infrastructure-505708 --region=europe-west2 \
  --update-env-vars=FAIL_RATE=0,LATENCY_MS=1500,APP_VERSION=v3-slow \
  --no-traffic --quiet
gcloud run services update-traffic sre-demo-shop \
  --project=personal-infrastructure-505708 --region=europe-west2 \
  --to-latest --quiet
```

Expected: checkout succeeds but takes roughly 1.5 seconds plus network overhead. Three consecutive verified probes above the watch's 1,000 ms limit trigger an investigation. The existing 5xx alarm does not detect this condition.

Ask:

> Requests are returning 200. Why does this deployment need attention? Compare checkout latency and the revision change.

Say: “Availability alone does not tell us whether the application is usable. We can apply our own release checks.”

## 3. Verify recovery without being fooled by old errors

The deployed cloud rollback executor is currently disabled. Recover as the operator using the CLI; do not present this as an agent-executed rollback or click-through approval demo.

If a watch is still active, first send:

> Stop the deployment watch.

Then recover:

```sh
python3 scripts/cloud/demo.py rollback
```

Type `rollback` when prompted. This routes traffic to the revision saved in `.demo-state`. Keep load running and ask:

> Verify recovery from fresh evidence on the revision serving now. Separate historical errors from current failures. Is there enough evidence to resolve this incident?

Expected: the agent names the restored revision and checks fresh logs and metrics. Telemetry can lag; an unknown result is a valid answer until sufficient evidence arrives. Use the UI's resolution control only after checking current checkout success, with a note describing the recovery. Resolve any separate alert investigation too.

Say: “Changing traffic is only half the job. We must verify the user journey recovered, and keep the incident history.”

## Optional short prompt

> How many requests did we serve in the last 24 hours? Break them down by response class and revision. State the latest metric timestamp and any gaps.

This uses request metrics for counts. A bounded log sample is not a traffic total. A metrics gap should produce an explicit limitation rather than an invented count.

## Recording checks

- Open and sign in to the cloud console before starting the take.
- Keep one watch active at a time. Do not redeploy the console during an investigation.
- Expect checks about every ten seconds, plus API and model time. Do not promise an instant diagnosis.
- For a delayed alarm, use the watch conversation to continue the demo and label that trigger accurately.
- Restore health after each failure, verify checkout, close the finished records, and stop load when recording ends.
- A passing release watch requires fresh, complete metrics as well as successful probes. Missing telemetry can leave the result inconclusive.
