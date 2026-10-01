from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from test_backend import store as store

from sre_agent.config import Settings
from sre_agent.deployment_watch import DeploymentWatches, watch_request
from sre_agent.main import create_app


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds=10):
        self.value += timedelta(seconds=seconds)


class Cloud:
    def __init__(self, clock):
        self.clock = clock
        self.revision = "shop-good"
        self.status = 200
        self.paid = True
        self.latency = 100
        self.probe_revision = None
        self.unavailable = False
        self.metric_errors = 0
        self.old_metrics = False
        self.no_metrics = False
        self.metrics_unavailable = False
        self.probe_count = 0

    def snapshot(self):
        return {"revision": self.revision, "url": "https://shop.example.run.app"}

    def probe(self, snapshot):
        self.probe_count += 1
        if self.unavailable:
            raise PermissionError("Probe not authorized")
        return {
            "status": self.status,
            "paid": self.paid,
            "latency_ms": self.latency,
            "revision": self.probe_revision or self.revision,
            "error": None,
        }

    def metrics(self, minutes):
        if self.metrics_unavailable:
            raise PermissionError("Metrics not authorized")
        end = self.clock() - timedelta(hours=1 if self.old_metrics else 0)
        points = (
            []
            if self.no_metrics
            else [
                {
                    "start": (end - timedelta(seconds=5)).isoformat(),
                    "end": end.isoformat(),
                    "revision": self.revision,
                    "labels": {"response_code_class": "5xx"},
                    "requests": self.metric_errors,
                }
            ]
        )
        return {
            "title": "Test metrics",
            "kind": "metrics",
            "url": "https://console.cloud.google.com/monitoring",
            "data": {"points": points},
        }


def make_watch(store, *, next_deployment=False, minutes=1):
    clock = Clock()
    cloud = Cloud(clock)
    manager = DeploymentWatches(store, cloud, clock)
    watch = manager.create(
        None,
        "watch-test-request",
        "Watch this deployment.",
        {"next_deployment": next_deployment, "minutes": minutes},
    )
    return manager, cloud, clock, watch["incident_id"]


def state(store, incident):
    return store.detail(incident)["incident"]["watch"]


def run_window(manager, clock):
    for _ in range(7):
        manager.tick()
        clock.advance()


@pytest.mark.parametrize(
    "command,expected",
    [
        ("Monitor the deploy", {"next_deployment": False, "minutes": 5}),
        ("Watch the next deployment for five minutes.", {"next_deployment": True, "minutes": 5}),
        ("Watch this deployment for 1 minute", {"next_deployment": False, "minutes": 1}),
        ("Stop the deployment watch.", {"stop": True}),
        ("Do not watch the next deployment", None),
        ("logs: Watch this deployment", None),
        ("Could you explain deployment monitoring?", None),
    ],
)
def test_only_explicit_operator_commands_are_scheduled(command, expected):
    assert watch_request(command) == expected


def test_policy_cannot_be_changed_by_extra_prose():
    command = (
        "Watch the next deployment for five minutes. "
        "Check checkout success, errors and latency. "
        "Investigate any regression and ask me before rolling back."
    )
    assert watch_request(command) == {"next_deployment": True, "minutes": 5}
    with pytest.raises(ValueError, match="separate request"):
        watch_request("Watch this deployment. Automatically rollback anything.")
    with pytest.raises(ValueError, match="1 and 15"):
        watch_request("Watch this deployment for 100 minutes.")


def test_next_deployment_waits_for_serving_change_and_survives_restart(store):
    manager, cloud, clock, incident = make_watch(store, next_deployment=True)
    manager.tick()
    assert state(store, incident)["status"] == "waiting"
    assert cloud.probe_count == 0
    cloud.revision = "shop-new"
    clock.advance()
    manager = DeploymentWatches(store, cloud, clock)  # New process resumes persisted state.
    manager.tick()
    watch = state(store, incident)
    assert watch["revision"] == "shop-new"
    assert watch["status"] == "watching"
    assert watch["deadline"] == clock() + timedelta(minutes=1)
    clock.advance()
    run_window(manager, clock)
    assert state(store, incident)["status"] == "passed"
    assert store.detail(incident)["incident"]["status"] == "active"
    assert store.claim() is None


def test_current_watch_passes_only_after_window_and_does_not_resolve_incident(store):
    manager, _, clock, incident = make_watch(store)
    manager.tick()
    assert state(store, incident)["status"] == "watching"
    assert store.summary()["attention"] == 0
    assert store.summary()["watching"] == 1
    clock.advance()
    run_window(manager, clock)
    watch = state(store, incident)
    assert watch["status"] == "passed"
    assert len(watch["observations"]) == 6
    assert store.summary()["watching"] == 0
    assert store.detail(incident)["incident"]["status"] == "active"
    assert "other endpoints" in store.detail(incident)["messages"][-1]["content"]


@pytest.mark.parametrize("failure", ["checkout", "latency"])
def test_three_consecutive_regressions_queue_one_investigation_without_mutation(store, failure):
    manager, cloud, clock, incident = make_watch(store)
    if failure == "checkout":
        cloud.status, cloud.paid = 500, False
    else:
        cloud.latency = 1500
    for _ in range(3):
        manager.tick()
        clock.advance()
    assert state(store, incident)["status"] == "failed"
    run = store.claim()
    assert run["incident_id"] == incident
    assert "shop-good" in run["question"]
    message = store.detail(incident)["messages"][-1]
    assert message["role"] == "system"
    assert message["content"] == "Deployment checks failed. Investigation queued to find the cause."
    manager.tick()
    assert store.claim() is None
    assert store.detail(incident)["incident"]["action"] is None


def test_metric_failure_is_scoped_to_revision_and_start_time(store):
    manager, cloud, clock, incident = make_watch(store)
    cloud.metric_errors, cloud.old_metrics = 10, True
    manager.tick()
    assert state(store, incident)["status"] == "watching"
    cloud.old_metrics = False
    clock.advance()
    manager.tick()
    assert state(store, incident)["status"] == "failed"
    assert "Metrics" in state(store, incident)["result"]


@pytest.mark.parametrize(
    "gap", ["probe", "metrics", "stale", "revision", "interrupt", "first_check"]
)
def test_missing_or_stale_observations_never_pass(store, gap):
    manager, cloud, clock, incident = make_watch(store)
    if gap == "probe":
        cloud.unavailable = True
    elif gap == "metrics":
        cloud.no_metrics = True
    elif gap == "stale":
        cloud.old_metrics = True
    elif gap == "revision":
        cloud.probe_revision = "shop-other"
    elif gap == "interrupt":
        manager.tick()
        clock.advance(50)
    else:
        clock.advance(50)
    run_window(manager, clock)
    assert state(store, incident)["status"] == "inconclusive"
    assert store.claim() is None


def test_revision_change_ends_watch_without_claiming_health(store):
    manager, cloud, _, incident = make_watch(store)
    cloud.revision = "shop-other"
    manager.tick()
    assert state(store, incident)["status"] == "inconclusive"
    assert cloud.probe_count == 0


def test_waiting_times_out_and_cancel_wins_over_inflight_read(store):
    manager, _, clock, incident = make_watch(store, next_deployment=True)
    clock.advance(901)
    manager.tick()
    assert state(store, incident)["status"] == "inconclusive"
    manager, cloud, clock, incident = make_watch_for_another_request(store)
    original = cloud.probe

    def cancel_during_probe(snapshot):
        manager.cancel(incident)
        return original(snapshot)

    cloud.probe = cancel_during_probe
    manager.tick()
    assert state(store, incident)["status"] == "cancelled"
    assert state(store, incident)["observations"] == []
    assert store.claim() is None


def make_watch_for_another_request(store):
    clock = Clock()
    cloud = Cloud(clock)
    manager = DeploymentWatches(store, cloud, clock)
    watch = manager.create(
        None,
        "another-watch-request",
        "Watch this deployment.",
        {"next_deployment": False, "minutes": 1},
    )
    return manager, cloud, clock, watch["incident_id"]


def test_api_chat_start_retry_stop_and_security(store):
    cloud = Cloud(Clock())
    app = create_app(
        Settings(_env_file=None), store=store, start_worker=False, deployment_cloud=cloud
    )
    with TestClient(app) as client:
        token = {"x-csrf-token": client.get("/api/status").json()["csrf_token"]}
        body = {
            "question": "Watch the next deployment for five minutes.",
            "request_id": "start-watch-through-chat",
        }
        assert client.post("/api/incidents", json=body).status_code == 403
        first = client.post("/api/incidents", json=body, headers=token)
        assert first.status_code == 201
        incident = first.json()["id"]
        assert client.post("/api/incidents", json=body, headers=token).json()["id"] == incident
        assert len(store.list_incidents()) == 1
        path = f"/api/incidents/{incident}"
        assert client.get(path).json()["incident"]["watch"]["status"] == "waiting"
        assert (
            client.post(path + "/close", json={"notes": "done"}, headers=token).status_code == 409
        )
        assert client.post(path + "/watch/stop").status_code == 403
        assert (
            client.post(
                path + "/watch/stop", headers={**token, "origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert client.post(path + "/watch/stop", headers=token).status_code == 200
        assert client.get(path).json()["incident"]["watch"]["status"] == "cancelled"
        assert (
            client.post(
                path + "/messages",
                headers=token,
                json={
                    "content": "Monitor this deployment for 1 minute.",
                    "request_id": "watch-again-123",
                },
            ).status_code
            == 202
        )
        assert (
            client.post(
                path + "/messages",
                headers=token,
                json={"content": "Stop the deployment watch.", "request_id": "stop-watch-123"},
            ).status_code
            == 202
        )
        assert store.claim() is None


def test_only_one_watch_is_active_and_creation_failures_leave_no_empty_incident(store):
    manager, _, _, incident = make_watch(store)
    with pytest.raises(ValueError, match="already active"):
        manager.create(
            None,
            "another-watch-123",
            "Watch this deployment.",
            {"next_deployment": False, "minutes": 1},
        )
    assert len(store.list_incidents()) == 1
    with pytest.raises(ValueError, match="another message"):
        manager.create(
            incident,
            "watch-test-request",
            "different command",
            {"next_deployment": False, "minutes": 1},
        )


def test_concurrent_start_retry_creates_only_one_conversation(store):
    clock = Clock()
    cloud = Cloud(clock)
    manager = DeploymentWatches(store, cloud, clock)
    barrier = Barrier(2)
    snapshot = cloud.snapshot

    def simultaneous_snapshot():
        barrier.wait(timeout=5)
        return snapshot()

    cloud.snapshot = simultaneous_snapshot

    def create():
        return manager.create(
            None,
            "concurrent-retry",
            "Watch this deployment.",
            {"next_deployment": False, "minutes": 1},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: create(), range(2)))
    assert first["id"] == second["id"]
    assert len(store.list_incidents()) == 1
    assert len(store.detail(first["incident_id"])["messages"]) == 2


def test_background_thread_checks_without_browser_or_model_execution(store):
    manager, cloud, _, incident = make_watch(store)
    checked = Event()
    probe = cloud.probe

    def record_probe(snapshot):
        result = probe(snapshot)
        checked.set()
        return result

    cloud.probe = record_probe
    manager.start()
    try:
        assert checked.wait(timeout=5)
    finally:
        manager.stop()
    assert state(store, incident)["observations"][0]["healthy"] is True
    assert store.claim() is None


def test_passed_watch_does_not_replay_checks_after_restart(store):
    manager, cloud, clock, incident = make_watch(store)
    run_window(manager, clock)
    count = cloud.probe_count
    DeploymentWatches(store, cloud, clock).tick()
    assert cloud.probe_count == count
    assert state(store, incident)["status"] == "passed"


def test_watch_blocks_existing_rollback_approval_until_cancelled(store):
    from test_rollback import cloud as rollback_cloud
    from test_rollback import ready

    from sre_agent.rollback import Rollbacks

    incident = ready(store)
    executor = Rollbacks(store, rollback_cloud())
    action = executor.propose(incident, "prior-proposal", "rollback")
    manager = DeploymentWatches(store, Cloud(Clock()), Clock())
    manager.create(
        incident,
        "watch-after-proposal",
        "Watch this deployment.",
        {"next_deployment": False, "minutes": 1},
    )
    with pytest.raises(ValueError, match="Stop the deployment watch"):
        executor.approve(incident, action["id"], "operator")
    manager.cancel(incident)
    executor.approve(incident, action["id"], "operator")


def test_probe_distinguishes_permission_errors_from_application_failures(monkeypatch):
    import io
    from urllib.error import HTTPError

    from sre_agent.deployment_watch import DeploymentCloud

    monkeypatch.setattr("sre_agent.deployment_watch.fetch_id_token", lambda *a: "test-token")
    cloud = DeploymentCloud(Settings(_env_file=None))
    snapshot = {"revision": "shop-new", "url": "https://shop.example.run.app"}
    fail = Mock(side_effect=HTTPError(snapshot["url"], 403, "Forbidden", {}, io.BytesIO(b"{}")))
    monkeypatch.setattr("sre_agent.deployment_watch.urlopen", fail)
    with pytest.raises(ValueError, match="access unavailable"):
        cloud.probe(snapshot)
    fail.side_effect = HTTPError(
        snapshot["url"],
        500,
        "Failed",
        {},
        io.BytesIO(b'{"revision":"shop-new","error":"PaymentConfigError"}'),
    )
    result = cloud.probe(snapshot)
    assert result["status"] == 500
    assert result["revision"] == "shop-new"
    assert result["paid"] is False


def test_unknown_check_breaks_failure_streak(store):
    manager, cloud, clock, incident = make_watch(store)
    cloud.status, cloud.paid = 500, False
    manager.tick()
    clock.advance()
    cloud.unavailable = True
    manager.tick()
    clock.advance()
    cloud.unavailable = False
    manager.tick()
    clock.advance()
    manager.tick()
    assert state(store, incident)["status"] == "watching"
    assert state(store, incident)["consecutive_failures"] == 2
    clock.advance()
    manager.tick()
    assert state(store, incident)["status"] == "failed"


def test_transient_metric_access_failure_is_not_hidden_by_later_success(store):
    manager, cloud, clock, incident = make_watch(store)
    cloud.metrics_unavailable = True
    manager.tick()
    cloud.metrics_unavailable = False
    clock.advance()
    run_window(manager, clock)
    assert state(store, incident)["status"] == "inconclusive"
    assert "Metrics access failed" in state(store, incident)["gap"]


def test_truncated_metrics_cannot_establish_pass(store):
    manager, cloud, clock, incident = make_watch(store)
    metrics = cloud.metrics

    def truncated(minutes):
        evidence = metrics(minutes)
        evidence["data"]["possibly_truncated"] = True
        return evidence

    cloud.metrics = truncated
    run_window(manager, clock)
    assert state(store, incident)["status"] == "inconclusive"
