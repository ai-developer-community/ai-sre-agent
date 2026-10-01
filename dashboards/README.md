# Golden signals

Open [AI SRE · Golden signals](https://console.cloud.google.com/monitoring/dashboards/builder/a4356e37-1ece-4b1e-881e-030137088439?project=personal-infrastructure-505708). Select the last hour and enable automatic refresh. Keep it beside the agent chat during the demo.

The four charts use real Cloud Run metrics for the demo shop in `europe-west2`:

- **Latency:** p95 latency for successful requests, by revision. The 1,000 ms line is the demo watch limit, not a production SLO. This metric measures container request processing; it excludes container startup time and is not the same as laptop round-trip latency.
- **Traffic:** requests per second, summed by revision.
- **Errors:** server failures per second, summed by revision. An absent 5xx series is not a complete health check.
- **Saturation:** p95 CPU utilization. CPU is only one saturation signal; it does not establish available concurrency, memory, database or downstream capacity.

These are service-wide metrics, not checkout-only metrics. The traffic generator mostly calls checkout. Metric ingestion can lag, and gaps must not be read as zero. Percentiles are computed for each Cloud Run time series rather than averaged across revisions.

For the slow deployment, show successful requests above the latency line while traffic continues. After approving rollback in the agent UI, keep traffic running and wait for fresh healthy-revision samples. The dashboard uses historical telemetry; the executor's five checkout probes verify recovery separately.

The deployed dashboard was validated on 1 October 2026: all four queries returned data, and the slow revision's p95 latency was approximately 1,555 ms. That is an observation, not a permanent health assertion.

To update the existing dashboard from the repository root:

```sh
gcloud monitoring dashboards update \
  projects/1004219842855/dashboards/a4356e37-1ece-4b1e-881e-030137088439 \
  --project=personal-infrastructure-505708 \
  --config-from-file=dashboards/golden-signals.json
```

To create a separate copy, use `gcloud monitoring dashboards create` with the same project and configuration flags. Creation makes a new dashboard each time.
