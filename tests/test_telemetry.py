from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from sre_agent.config import Settings
from sre_agent.telemetry import Telemetry, sanitize, window


def test_redacts_structured_and_text_secrets_and_bounds_output():
    result = sanitize(
        {
            "authorization": "Bearer abc",
            "nested": [{"api_key": "value"}],
            "message": "password=hunter2 token=abc Bearer abc.def",
            "long": "x" * 4000,
            "rows": list(range(200)),
        }
    )
    assert result["authorization"] == "[redacted]"
    assert result["nested"] == [{"api_key": "[redacted]"}]
    assert "hunter2" not in result["message"]
    assert "abc" not in result["message"]
    assert len(result["long"]) == 3000
    assert len(result["rows"]) == 100


def test_queries_clamp_time_window():
    start, end = window(10000)
    assert (end - start).total_seconds() == 3600
    start, end = window(-50)
    assert (end - start).total_seconds() == 300


def test_empty_metrics_are_unknown_and_query_is_scoped(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    client.list_time_series.return_value = []
    monkeypatch.setattr("sre_agent.telemetry.monitoring_v3.MetricServiceClient", lambda: client)
    telemetry = Telemetry(
        Settings(
            _env_file=None,
            project_id="test-project",
            shop_service="test-shop",
            region="europe-west2",
        )
    )
    data = telemetry.metrics()["data"]
    assert data["latest_sample"] is None
    assert data["points"] == []
    assert "unknown, never healthy" in data["note"]
    request = client.list_time_series.call_args.kwargs["request"]
    assert request["name"] == "projects/test-project"
    assert 'service_name="test-shop"' in request["filter"]
    assert 'location="europe-west2"' in request["filter"]


def test_deployment_audit_excludes_request_secrets(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    client.list_entries.return_value = [
        SimpleNamespace(
            timestamp=datetime.now(timezone.utc),
            payload={
                "methodName": "UpdateService",
                "resourceName": "shop",
                "authenticationInfo": {"principalEmail": "operator@example.com"},
                "request": {"env": {"PASSWORD": "very-private"}},
            },
        )
    ]
    monkeypatch.setattr("sre_agent.telemetry.logging_v2.Client", lambda **kwargs: client)
    result = Telemetry(Settings(_env_file=None)).deploy_logs()
    assert "very-private" not in str(result)
    assert result["data"]["entries"][0]["method"] == "UpdateService"


def test_metrics_explicitly_report_truncation_after_more_than_100_points(monkeypatch):
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    client = MagicMock()
    client.__enter__.return_value = client
    series = []
    for revision in ("v1", "v2"):
        series.append(
            SimpleNamespace(
                metric=SimpleNamespace(labels={"response_code_class": "5xx"}),
                resource=SimpleNamespace(labels={"revision_name": revision}),
                points=[
                    SimpleNamespace(
                        interval=SimpleNamespace(
                            end_time=now - timedelta(minutes=i),
                            start_time=now - timedelta(minutes=i + 1),
                        ),
                        value=SimpleNamespace(int64_value=10),
                    )
                    for i in range(60)
                ],
            )
        )
    client.list_time_series.return_value = series
    monkeypatch.setattr("sre_agent.telemetry.monitoring_v3.MetricServiceClient", lambda: client)
    result = sanitize(Telemetry(Settings(_env_file=None)).metrics())["data"]
    assert result["possibly_truncated"] is True
    assert result["returned_points"] == result["point_limit"] == len(result["points"]) == 100
    assert result["latest_sample"] == now.isoformat()
    assert "do not compute a whole-window rate" in result["note"]
    assert [p["end"] for p in result["points"]] == sorted(
        [p["end"] for p in result["points"]],
        reverse=True,
    )


def test_revision_request_matches_installed_google_client_signature(monkeypatch):
    from unittest.mock import create_autospec

    from google.cloud import run_v2

    # Autospec preserves the real method signature: a top-level page_size raises TypeError.
    revisions = create_autospec(run_v2.RevisionsClient, instance=True)
    revisions.__enter__.return_value = revisions
    revisions.list_revisions.return_value = []
    services = create_autospec(run_v2.ServicesClient, instance=True)
    services.__enter__.return_value = services
    services.get_service.return_value = SimpleNamespace(traffic_statuses=[])
    monkeypatch.setattr("sre_agent.telemetry.run_v2.RevisionsClient", lambda: revisions)
    monkeypatch.setattr("sre_agent.telemetry.run_v2.ServicesClient", lambda: services)
    settings = Settings(_env_file=None, project_id="test-project", shop_service="test-shop")
    result = Telemetry(settings).revisions()
    assert result["data"]["revisions"] == []
    kwargs = revisions.list_revisions.call_args.kwargs
    # Validate the request's field names using the actual Google protobuf message.
    request = run_v2.ListRevisionsRequest(kwargs["request"])
    assert request.parent == "projects/test-project/locations/europe-west2/services/test-shop"
    assert request.page_size == 20
    assert kwargs["timeout"] == 30
