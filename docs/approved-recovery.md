# Hosted incident and recovery demo

The console and agent run on Cloud Run. The browser UI shows all active incidents, how many need attention, and how many have queued/running investigations. An investigation finishing does not establish health. The incident remains amber until a person closes it or approved rollback passes its checkout checks.

## Recording flow

1. Open the private console. With IAP enabled, use the Cloud Run HTTPS URL and sign in with the permitted Google account. The local proxy remains an option before IAP is enabled; CLI login alone does not sign a browser into a private Cloud Run service.
2. Run `python3 scripts/cloud/demo.py deploy-healthy` to establish a fresh healthy revision. Deploy the console with that exact saved revision as `--rollback-revision`. Keep `--model claude-opus-5-5` and the Vertex region `global`.
3. Run `python3 scripts/load.py SHOP_URL --authenticated --rps 5` using the healthy deployment's printed URL. Keep the load running.
4. Run `python3 scripts/cloud/demo.py deploy-broken`. Monitoring requires errors above 0.2 per second for 60 seconds; telemetry delivery and the model investigation add delay. The UI shows queued/investigating before it presents a diagnosis. Do not promise instant root-cause certainty.
5. Open the new alert incident. Show the findings, evidence and activity. Ask what changed or challenge the proposed cause if useful.
6. Send exactly `rollback the change`. The backend reads Cloud Run and prepares a proposal naming the current and target revisions. The model cannot execute mutations or turn log text into approval.
7. Click **Approve** on the inline Rollback card. **Deny** records the decision without changing traffic and leaves the incident open. The backend rechecks the exact plan, updates only the demo shop's traffic, and runs five authenticated checkout requests. The UI shows rolling back, then verifying recovery.
8. Only successful checkout checks, expected version, and target traffic confirmation resolve the incident and show **Recovery verified**. The UI records the verification time. Monitoring can take longer to close its alarm.
9. Stop the load generator with Ctrl-C. Cloud SQL and the minimum Cloud Run instance remain chargeable until deliberately paused or removed.

A later failure creates a new incident. Resolved records show the outcome of their own recovery checks; they do not claim that production remains healthy forever.

## Access and deployment

Run commands from the repository root. These are explicit cloud access changes; do not run them for client projects. The browser access setup is separate from the rollback setup.

```sh
python3 scripts/cloud/access.py browser --user APPROVED_OPERATOR_EMAIL
python3 scripts/cloud/access.py rollback
python3 scripts/cloud/hosted.py deploy --model claude-opus-5-5 --vertex-region global --rollback-revision VERIFIED_SHOP_REVISION
```

Replace `APPROVED_OPERATOR_EMAIL` with the approved Google account. Replace `VERIFIED_SHOP_REVISION` with `healthy_revision` in `.demo-state` after a successful healthy deployment. `SHOP_URL` is that state's `url`. No credentials belong in these arguments.

Browser access uses Google IAP, restricted to the named operator. Google's managed IAP identity receives invoker access on the console. No public principal is added. The installed CLI currently exposes direct IAP configuration through `gcloud beta run services update --iap`.

Rollback access adds a custom role containing `run.services.get` and `run.services.update`, bound only on `sre-demo-shop`, plus shop invocation permission for authenticated synthetic checkouts. IAM's update permission permits broader service updates than traffic changes; the executor code restricts the request mask to `traffic`. This is not field-level IAM isolation. The agent and executor share a backend service identity, but the SDK exposes only its four read tools and no shell. A separate executor identity/service is an extension for broader production use.

## State and failure handling

`rollback_actions` is an additive PostgreSQL table. Proposals expire after five minutes. Approval is bound to its saved project/service, serving revision, target, URL and Cloud Run etag. Changed state or configuration rejects execution. Split traffic and reconciling deployments are rejected. The target is explicitly configured from the operator's verified healthy deployment and must have the demo's healthy configuration.

Approval is idempotent and only one approved/running/verifying rollback is permitted at a time. The worker durably claims actions and does not automatically replay an interrupted mutation. A timeout or restart can mean traffic changed without confirmation, so it keeps the incident active and asks the operator to inspect current state. Fresh proposals are required for retries.

Cloud Run traffic updates use the saved etag to reject conflicting changes. Operator approval, execution results and checkout observations are stored with the incident. A successful recovery transaction locks the incident, cancels queued notification follow-ups and resolves it. Late notifications cannot reopen that record.

A successful recovery proves five synthetic checkout successes and the observed traffic assignment. It does not prove an SLO, verify database migration compatibility, or clear delayed historical error metrics. This workflow is deliberately restricted to the fake shop, which performs no real payments.
