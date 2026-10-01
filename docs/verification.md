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

## 2026-09-30 approved recovery and overview

- 42 Python tests pass against isolated PostgreSQL schemas, including approval, denial, stale revision, expiry, restart and concurrent notification cases.
- 6 frontend tests pass; production build, Ruff and diff whitespace checks pass.
- Independent review found no remaining actionable issues after concurrency fixes.
- Browser checks cover desktop and 390px mobile overview, incident navigation, plain context controls, consistent chat spacing, and an isolated approval/denial/recovery fixture. The fixture does not prove live cloud recovery.
- Hosted Claude Opus 5.5 configuration and incident counts were verified through the authenticated console proxy.
- Direct browser IAP access and runtime shop rollback permissions remain pending explicit access-change approval. The hosted executor remains disabled. A real bad-deployment/approved-rollback rehearsal is still required after enabling those permissions.

## 2026-09-30 browser access enabled

The operator explicitly approved console browser access. IAP is enabled; its service identity has console invoker access. The saved console-specific IAP policy grants `owain@gradientwork.com` the accessor role. An unauthenticated request returns HTTP 302 to `accounts.google.com`. The signed-in browser session has not yet been exercised. Runtime shop rollback permissions still require separate approval. The setup script uses beta IAP commands supported by the installed CLI and enables both required APIs. Two focused access tests and Ruff pass.

## 2026-10-01 chat deployment watches

Cloud deployment and a real deployment-watch rehearsal remain **unverified**:
the operator's gcloud session requires reauthentication. Private checkout probes
also need the hosted identity to have demo-shop invoker access. Earlier shop
revisions do not return the new revision field; redeploy the updated shop before
recording this feature. This work does not enable the hosted rollback executor.

- **75 Python tests pass**, using real PostgreSQL with isolated schemas. The
  watch tests cover persistent restart, concurrent retries, an independent
  background thread, cancellation during an in-flight check, revision matching,
  checkout and latency regressions, metric freshness, missing access, truncation
  and prevention of conflicting rollback approval.
- **7 frontend tests**, Ruff, production build and diff whitespace checks pass.
- Independent review approved the implementation and final display-payload fix.
- A real browser exercised the local application with an isolated fake-cloud
  fixture: start from chat, waiting for a revision, monitoring after deployment,
  persistence across navigation/reload, dashboard count, Stop watching, and
  three failed checkouts queuing investigation. The final failed card shows
  HTTP status and latency; chat shows a concise system notification while the
  queued model request retains the full evidence. Browser DOM evidence was
  captured in `/tmp/deployment-watch-browser-evidence.txt` during verification.
  These checks do not establish live Cloud Run or Claude behavior. The new
  component was visually checked at desktop size; mobile layout and browser
  console errors were not independently verified for this change.
- Recovery remains separately requested and approved. A passed watch does not
  close an incident or claim that all application endpoints are healthy.

The full video outline and three Mermaid diagrams are in
[video-outline.md](video-outline.md); the operator command and recording
requirements are in [deployment-watch.md](deployment-watch.md).
