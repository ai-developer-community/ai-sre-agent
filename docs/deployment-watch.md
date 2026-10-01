# Watch a deployment from chat

The console can schedule a persistent, read-only watch for its configured Cloud
Run application. Checks continue when the browser closes. The model is used to
investigate a failed watch; application code schedules and evaluates the checks.
There is no automatic rollback.

## Commands

Start a new conversation, or send one of these in an existing active conversation:

```text
Watch the next deployment for five minutes.
```

This records the current serving revision and waits up to 15 minutes for a
revision change. When a different revision serves 100% of traffic, its observation
window starts. Deploying a revision with zero traffic does not start the window.

```text
Watch this deployment for five minutes.
```

This starts watching the revision currently serving 100% of traffic. `Monitor the
deploy` is also supported and defaults to five minutes. Durations accept digits
from 1 to 15, plus the supported number words shown in the starter command. Chat
recognition uses explicit commands, not general natural-language planning.

The full video prompt is supported:

```text
Watch the next deployment for five minutes. Check checkout success, errors and latency. Investigate any regression and ask me before rolling back.
```

The extra sentences describe the fixed policy; they cannot change it. Arbitrary
additional instructions are rejected rather than silently changing approval
rules. General questions go to the investigator, which can suggest the command
but has no tool to start a watch itself.

Send `Stop the deployment watch.` or use **Stop watching** to cancel. Stop works
even while the model is investigating. Stop the watch before resolving this
conversation or proposing/approving a rollback in it.

## What gets checked

One watch can be active for the configured application. Approximately every ten
seconds, excluding API time, the background watcher:

1. Reads Cloud Run state. Split traffic and a reconciling service cannot establish
   a verified observation.
2. Makes an authenticated `POST /checkout` to the fixed demo service URL.
3. Checks the HTTP status, `paid` outcome, elapsed request time and response
   revision. It re-reads serving state to detect changes during the request.
4. Reads request-count metrics over the watch duration plus one minute, with a
   minimum five-minute query window. Only buckets starting after the watch began
   and belonging to the watched revision count toward the failure criterion.
5. Saves the observations and bounded metric evidence in Postgres.

The shop response includes `revision` from Cloud Run's `K_REVISION`, on successful
and failed checkout responses. Older shop revisions without this field cannot
produce a verified result. Deploy the updated shop before a passing rehearsal.

The fixed demo failure policy is three consecutive verified checkout failures,
three consecutive verified requests over 1,000 ms, or at least three observed
5xx metric counts after the watch started. An unavailable or unverified check
breaks a failure streak. Invocation failures such as 403 are an access gap, not
an application regression.

A failure stops the watch and queues the existing read-only investigator in the
same conversation. It does not prepare, approve or execute a rollback.

## Outcomes

- **Passed:** all collected checkout probes were verified, successful and within
  the latency limit; at least three probes were collected; final matching metrics
  were complete and no more than two minutes old; no access/interruption gap was
  recorded. This validates only the sampled checkout requests and observation
  window, not every request or application endpoint.
- **Failed:** a defined failure criterion was met. An investigation is queued.
- **Inconclusive:** evidence was insufficient, checks were interrupted for more
  than 45 seconds, revision changed, no deployment appeared, or observations were
  unverified, unhealthy or stale without meeting the failure threshold.
- **Cancelled:** the operator stopped the watch. In-flight reads cannot reactivate
  it or queue an investigation after cancellation.

Metrics can lag. Empty early reads can be filled by subsequent reads over the
whole window. Metric access failures remain recorded gaps. Use three to five
minutes for a healthy-pass recording. A one-minute watch is useful for detecting
repeated immediate failures, but often ends before a full post-start metric
bucket becomes available and should then report inconclusive.

Passing never automatically resolves an incident or asserts production-wide
health. The dashboard and conversation distinguish a running watch from an
investigation and an incident needing attention.

## Runtime and permissions

The watcher is a separate background thread with a PostgreSQL leadership lock,
so a slow Claude investigation cannot block its timed checks. Watch state,
deadlines and observations survive a restart; substantial gaps prevent a pass.
Completed watches are not replayed. The server needs CPU allocated outside HTTP
requests and a minimum running instance, as configured by the hosted demo.

The runtime requires its existing Cloud Run/Monitoring read access and
`roles/run.invoker` on the private demo shop to make checkout probes. The watcher
has no infrastructure mutation calls. Hosted token generation uses the attached Cloud Run identity. For local probes,
`fetch_id_token` requires a supported service-account or impersonation credential
configuration explicitly selected with `GOOGLE_APPLICATION_CREDENTIALS`; ordinary
gcloud login or application-default login alone is insufficient. Do not create
service-account keys for this demo. Local tests use isolated test doubles.

The optional rollback executor still requires separate explicit configuration
and permission approval. Adding checkout invocation access does not enable it.

## Rehearse

From the repository root, with gcloud authenticated:

1. Deploy the updated healthy shop using `python3 scripts/cloud/demo.py deploy-healthy`.
2. Run real synthetic traffic as documented in [the rehearsal guide](demo-rehearsal.md).
3. Send `Watch the next deployment for five minutes.` in chat.
4. Run `python3 scripts/cloud/demo.py deploy-broken`.
5. Observe waiting → monitoring → failed → investigating. Open checkout evidence.
6. Restore the verified revision using the manual rollback command, or the
   separately configured approved workflow. Verify checkout and inspect current
   metrics before resolving.

For the healthy scene, deploy another healthy revision while a next-deployment
watch is waiting, then let the full window finish. Don't fast-forward the server
clock or present a fixture as cloud evidence.

See [the video outline](video-outline.md) for narration and architecture diagrams.
