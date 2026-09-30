# V1 verification

Verified on 29 September 2026. Passing infrastructure checks do not establish a successful model investigation.

## Local checks

- **30 tests passed** on Python 3.12 with real PostgreSQL 17 and isolated test schemas.
- Ruff and the React production build passed.
- Tests cover duplicate delivery, closure races, missing metrics, Google client compatibility, hosted host/origin boundaries, worker handover and selecting a new deployment when traffic is pinned to an older revision.
- Independent review approved the hosted code after correcting the proxy hostname allowlist. A later live rehearsal found the pinned-revision issue; its fix and regression test were also reviewed and approved.

## Cloud checks

- Provisioned the demo-only Pub/Sub topic/subscription, Monitoring policy/channel, investigator/shop/builder identities, Cloud SQL instance and Secret Manager database URL in `personal-infrastructure-505708`.
- Built and deployed the non-root console container to private Cloud Run. The hosted API responds through the authenticated gcloud proxy, connects to Cloud SQL, and reports no worker error.
- Unauthenticated console access returns **403**. The real browser loads the hosted UI and accurately shows missing model configuration.
- Deployed the private shop and verified **200** on an authenticated healthy checkout. The organisation rejects public IAM principals, so the rehearsal uses authenticated requests instead of changing that policy.
- The broken revision produces **500** checkout responses and real `PaymentConfigError` logs. Monitoring's exact configured aggregation shows a sustained rate around two server errors per second, exceeding the 0.2/s threshold.
- Monitoring opened incident `0.od7ggjluokvv` at 21:19:20 UTC. Its real notification arrived on `sre-demo-agent` with the expected project, service and region labels. The hosted subscriber persisted that real incident in Cloud SQL. An earlier revision attempted it before the model was configured and recorded an explicit configuration failure, without a diagnosis. The final revision pauses new investigations until a model is configured.

- Rolled traffic back to healthy revision `sre-demo-shop-00001-jhj`; authenticated health and checkout requests both returned **200**, with a paid checkout result. Monitoring independently closed the alarm at 21:27:00 UTC.

## Model access remains blocked

The operator's Vertex probes returned HTTP 404 (model not found or no project access) for Sonnet 4.6 global/us-east5, Sonnet 4.5 global and Haiku 4.5 global. No successful model call has been demonstrated. The hosted console therefore queues real incoming alerts with its model worker paused, clearly showing the configuration gap.

Enable an available Claude model in Vertex Model Garden for this project, then redeploy with its exact model ID. Complete SDK-to-MCP execution, a supported diagnosis and post-rollback model verification remain unverified. SDK unit tests use test doubles and do not prove model accuracy. The earlier cloud approval block was superseded by the user's explicit deployment request; these resources are now real and incur ongoing charges.
