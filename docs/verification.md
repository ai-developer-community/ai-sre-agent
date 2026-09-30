# V1 verification

Verified locally on 29 September 2026. This records what was tested, not a claim that the live cloud demonstration has passed.

## Local proof

- Final Python 3.12 run: **24 tests passed**. Ruff and the production frontend build passed.
- Python tests use real PostgreSQL 17 with isolated, temporary schemas for persistence, idempotency, queueing and closure. SDK and cloud responses in unit tests are test doubles, not recorded production evidence.
- Ruff checks the backend, tests, shop and scripts. The React production bundle builds with Vite.
- A real browser exercised manual investigation creation, the visible missing-model failure, human resolution notes and closure. Reloading preserved the incident. The updated UI disables chat until a model is configured and displays the setup requirement.
- Desktop (1440 × 1000) and mobile (390 × 844) viewport captures were inspected. Empty evidence, connection status and missing-model states use real backend responses. No invented diagnosis or telemetry was inserted into the demo.
- Independent code review found and corrected a Google revision-client call signature, silent metrics truncation and a race between alert intake and human closure. The reviewer approved those corrections.

## Still requires a live rehearsal

- Refresh Application Default Credentials. The existing application credentials failed reauthentication; a working `gcloud` CLI login does not establish working ADC.
- Select and enable a Claude model, set its exact model ID, and pass `python -m sre_agent.doctor`.
- Provision the scoped demo resources and Cloud Run shop, then verify actual Pub/Sub delivery and the complete SDK-to-MCP investigation.
- Rehearse healthy traffic, broken checkout, agent investigation, manual rollback and evidence of recovery. Alert delays and model diagnosis quality remain unmeasured.

Cloud provisioning was stopped by automatic approval review because it creates IAM grants and a public Cloud Run service in the personal project. No cloud resources were changed by that attempt. Explicit approval is pending. Do not describe the demo as recording-ready until the live rehearsal passes.
