# Cloud demo scripts

These commands change only the named demo resources in project `personal-infrastructure-505708`, region `europe-west2`. They never change the active gcloud project. Setup adds IAM grants; it does not replace project policies. Inspect the script before running it. No Cloud SQL instance is created: Postgres runs locally.

1. Authenticate the operator with `gcloud auth login`.
2. Run `python scripts/cloud/demo.py setup` to enable APIs, create Pub/Sub, service accounts, a Monitoring notification channel and a service-wide 5xx alert.
3. Run `python scripts/cloud/demo.py deploy-healthy`. This deploys a public, non-sensitive shop, explicitly moves all traffic to its new revision, verifies a real checkout, and records that revision in `.demo-state`.
4. Run `python scripts/load.py SHOP_URL --rps 5` in another terminal and keep it running throughout the demo. Requests are actual Cloud Run traffic and incur normal cloud costs.
5. Run `python scripts/cloud/demo.py deploy-broken`. All checkout requests now produce a structured `PaymentConfigError`; process liveness remains healthy.
6. Wait for Monitoring and Pub/Sub, then investigate in the local console. The policy requires a service-wide 5xx rate greater than 0.2/s for 60 seconds, using a 60-second alignment window. Aggregation retains project, service and location labels so incident ingestion can validate the alert scope. Metric ingestion and notifications can add several minutes.
7. If a manual fallback is needed, run `python scripts/cloud/demo.py rollback` and type `rollback` at its explicit prompt. It targets the checkout-verified healthy revision recorded in `.demo-state`. The command only changes traffic; it does not assert recovery.
8. Keep load running and inspect fresh telemetry to establish recovery. Repeat `deploy-broken` for the next take. Each deployment explicitly moves traffic because a rollback pins traffic to a revision.

The shop service account receives no project roles. The investigator service account receives `logging.viewer`, `monitoring.viewer`, `run.viewer`, plus subscriber access on the demo subscription only. A custom `sreDemoPredict` role grants only `aiplatform.endpoints.predict` and `serviceusage.services.use` for model calls. Setup refuses to reuse that role if its permission set differs. Claude model availability still needs a real authenticated probe.

Local ADC is separate from CLI login. For read-only investigator credentials, an administrator can grant the operator `roles/iam.serviceAccountTokenCreator` **on the investigator service account**, then run:

```sh
gcloud auth application-default login \
  --impersonate-service-account=sre-demo-investigator@personal-infrastructure-505708.iam.gserviceaccount.com
```

The script does not grant impersonation access automatically. The operator's gcloud credentials deploy and perform manual rollback. Do not hand the agent a general shell tool with those operator credentials.

Setup is rerunnable. It refuses duplicate named Monitoring resources or a channel pointing to an unexpected topic. Existing named subscriptions must match the expected topic. The setup updates the named demo alert policy to the documented threshold. Cloud Run source deployment requires an operator with build/deploy permissions and a build service account configured for source builds; setup does not widen the operator's permissions to solve an authorization failure.

References: [Pub/Sub notifications](https://docs.cloud.google.com/monitoring/support/notification-options), [alert policy API](https://docs.cloud.google.com/monitoring/api/ref_v3/rest/v3/projects.alertPolicies), [Cloud Run traffic migration](https://docs.cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration).
