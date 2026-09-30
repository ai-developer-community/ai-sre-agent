"""A deliberately small read-only Google Cloud tool surface."""

import itertools
import re
from contextlib import closing
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

from google.cloud import logging_v2, monitoring_v3, run_v2

SECRET = re.compile(
    r"(?i)(bearer\s+)[\w.\-]+|((?:password|secret|api[_-]?key|token)\s*[=:]\s*)[^\s,;]+"
)


def sanitize(value):
    if isinstance(value, dict):
        return {
            str(k): "[redacted]"
            if re.search(r"(?i)password|secret|token|authorization|api[_-]?key", str(k))
            else sanitize(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value[:100]]
    if isinstance(value, str):
        return SECRET.sub(lambda m: (m.group(1) or m.group(2) or "") + "[redacted]", value)[:3000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:3000]


def window(minutes):
    minutes = max(5, min(60, int(minutes)))
    end = datetime.now(timezone.utc)
    return end - timedelta(minutes=minutes), end


def logs_url(project, filter_, start, end):
    return (
        "https://console.cloud.google.com/logs/query;query="
        + quote(filter_, safe="")
        + ";timeRange="
        + quote(f"{start.isoformat()}/{end.isoformat()}", safe="")
        + "?project="
        + quote(project, safe="")
    )


class Telemetry:
    def __init__(self, settings):
        self.settings = settings

    def logs(self, minutes=30, errors_only=True):
        start, end = window(minutes)
        s = self.settings
        filter_ = (
            f'resource.type="cloud_run_revision" '
            f'AND resource.labels.service_name="{s.shop_service}" '
            f'AND resource.labels.location="{s.region}" '
            f'AND timestamp>="{start.isoformat()}" AND timestamp<="{end.isoformat()}"'
        )
        if errors_only:
            filter_ += " AND severity>=ERROR"
        with closing(logging_v2.Client(project=s.project_id)) as client:
            entries = list(
                client.list_entries(
                    filter_=filter_, order_by="timestamp desc", max_results=40, page_size=40
                )
            )
        rows = [
            sanitize(
                {
                    "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                    "severity": e.severity,
                    "payload": e.payload,
                    "resource": e.resource.labels,
                }
            )
            for e in entries
        ]
        return {
            "title": "Checkout and service error logs" if errors_only else "Recent service logs",
            "url": logs_url(s.project_id, filter_, start, end),
            "kind": "logs",
            "data": {
                "filter": filter_,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "entries": rows,
                "limit": 40,
                "possibly_truncated": len(rows) == 40,
                "note": "An empty result does not establish health or traffic.",
            },
        }

    def metrics(self, minutes=15):
        start, end = window(minutes)
        s = self.settings
        filter_ = (
            f'resource.type="cloud_run_revision" '
            f'AND resource.labels.service_name="{s.shop_service}" '
            f'AND resource.labels.location="{s.region}" '
            'AND metric.type="run.googleapis.com/request_count"'
        )
        with monitoring_v3.MetricServiceClient() as client:
            pager = client.list_time_series(
                request={
                    "name": f"projects/{s.project_id}",
                    "filter": filter_,
                    "interval": {"start_time": start, "end_time": end},
                    "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                    "page_size": 100,
                },
                timeout=30,
            )
            series = list(itertools.islice(pager, 101))
        points = []
        for item in series[:100]:
            for point in item.points[:60]:
                points.append(
                    {
                        "end": point.interval.end_time.isoformat(),
                        "start": point.interval.start_time.isoformat(),
                        "requests": point.value.int64_value,
                        "labels": dict(item.metric.labels),
                        "revision": item.resource.labels.get("revision_name"),
                    }
                )
        point_truncated = len(points) > 100 or any(len(item.points) > 60 for item in series[:100])
        points = sorted(points, key=lambda p: p["end"], reverse=True)[:100]
        latest = max((p["end"] for p in points), default=None)
        return {
            "title": "Cloud Run request counts by response class and revision",
            "kind": "metrics",
            "url": "https://console.cloud.google.com/monitoring/metrics-explorer?"
            + urlencode({"project": s.project_id}),
            "data": {
                "filter": filter_,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "latest_sample": latest,
                "points": points,
                "possibly_truncated": len(series) > 100 or point_truncated,
                "point_limit": 100,
                "returned_points": len(points),
                "note": "Service-wide delta counts, not checkout-only. Metrics can lag. "
                "If truncated, do not compute a whole-window rate from this sample. "
                "Open Metrics Explorer and paste the provided filter. "
                "Missing or old samples are unknown, never healthy.",
            },
        }

    def revisions(self):
        s = self.settings
        name = f"projects/{s.project_id}/locations/{s.region}/services/{s.shop_service}"
        with run_v2.ServicesClient() as client:
            service = client.get_service(name=name, timeout=30)
        with run_v2.RevisionsClient() as client:
            revisions = list(
                itertools.islice(
                    client.list_revisions(request={"parent": name, "page_size": 20}, timeout=30),
                    20,
                )
            )
        rows = []
        for rev in revisions:
            rows.append(
                {
                    "name": rev.name.rsplit("/", 1)[-1],
                    "created_at": rev.create_time.isoformat(),
                    "images": [c.image for c in rev.containers],
                    "environment_names": sorted({e.name for c in rev.containers for e in c.env}),
                    "note": "Environment values deliberately withheld. "
                    "Revision existence does not prove it was healthy.",
                }
            )
        traffic = [{"revision": t.revision, "percent": t.percent} for t in service.traffic_statuses]
        return {
            "title": "Shop revisions and serving traffic",
            "kind": "deployment",
            "url": f"https://console.cloud.google.com/run/detail/{s.region}/{s.shop_service}"
            f"/revisions?project={s.project_id}",
            "data": {
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "traffic": traffic,
                "revisions": rows,
                "limit": 20,
            },
        }

    def deploy_logs(self, minutes=60):
        start, end = window(minutes)
        s = self.settings
        filter_ = (
            f'protoPayload.serviceName="run.googleapis.com" '
            f'AND protoPayload.resourceName="projects/{s.project_id}/locations/'
            f'{s.region}/services/{s.shop_service}" '
            'AND (protoPayload.methodName:"UpdateService" OR '
            'protoPayload.methodName:"ReplaceService" OR '
            'protoPayload.methodName:"CreateService") '
            f'AND timestamp>="{start.isoformat()}" AND timestamp<="{end.isoformat()}"'
        )
        with closing(logging_v2.Client(project=s.project_id)) as client:
            entries = list(
                client.list_entries(
                    filter_=filter_, order_by="timestamp desc", max_results=20, page_size=20
                )
            )
        # Do not expose raw audit request configs: these can contain credentials in env values.
        rows = []
        for entry in entries:
            payload = entry.payload if isinstance(entry.payload, dict) else {}
            rows.append(
                {
                    "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                    "method": payload.get("methodName"),
                    "resource": payload.get("resourceName"),
                    "principal": payload.get("authenticationInfo", {}).get("principalEmail"),
                }
            )
        return {
            "title": "Recent Cloud Run deployment audit events",
            "kind": "deployment",
            "url": logs_url(s.project_id, filter_, start, end),
            "data": {"filter": filter_, "entries": rows, "limit": 20},
        }
