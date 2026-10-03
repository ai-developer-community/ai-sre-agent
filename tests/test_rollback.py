from datetime import timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from test_backend import store as store

from sre_agent.config import Settings
from sre_agent.main import create_app
from sre_agent.rollback import RollbackCloud, Rollbacks, rollback_request
from sre_agent.store import actions, now
from sre_agent.worker import Worker


def ready(store):
    incident = store.create_incident("Checkout failures", "Investigate")
    store.finish(store.claim(), "Checkout failures coincide with revision bad.")
    return incident


def cloud():
    fake = Mock()
    fake.plan.return_value = {
        "service": "projects/demo/locations/europe-west2/services/shop",
        "revision": "shop-bad",
        "target": "shop-good",
        "etag": "version-1",
        "url": "https://shop.example.run.app",
    }
    fake.execute.return_value = {
        "revision": "shop-good",
        "verified_at": now().isoformat(),
        "checkout_checks": [{"status": 200}] * 5,
        "scope": "Fresh checkout checks passed.",
    }
    return fake


def test_only_explicit_operator_command_prepares_rollback():
    for text in ("rollback the change", "Roll back the deployment.", "please rollback"):
        assert rollback_request(text)
    for text in ("Should we rollback?", "Do not rollback", "logs: rollback the change", "yes"):
        assert not rollback_request(text)


def test_api_proposal_approval_verification_and_repeat_are_safe(store, monkeypatch):
    monkeypatch.setattr(Worker, "start", lambda _: None)
    monkeypatch.setattr(Worker, "stop", lambda _: None)
    provider = cloud()
    settings = Settings(_env_file=None, claude_model="test", rollback_revision="shop-good")
    app = create_app(settings, store=store, rollback_cloud=provider)
    incident = ready(store)
    with TestClient(app) as client:
        token = {"x-csrf-token": client.get("/api/status").json()["csrf_token"]}
        path = f"/api/incidents/{incident}"
        proposal = client.post(
            path + "/messages",
            headers=token,
            json={"content": "rollback the change", "request_id": "rollback-request-1"},
        )
        assert proposal.status_code == 202
        action_id = proposal.json()["action"]["id"]
        provider.execute.assert_not_called()
        assert client.get("/api/status").json()["incidents"]["attention"] == 1
        approve = path + f"/actions/{action_id}/approve"
        assert client.post(approve).status_code == 403
        assert (
            client.post(approve, headers={**token, "origin": "https://evil.example"}).status_code
            == 403
        )
        assert client.post(approve, headers=token).status_code == 202
        assert client.post(approve, headers=token).status_code == 202
        assert (
            client.post(path + "/close", headers=token, json={"notes": "done"}).status_code == 409
        )
        assert (
            client.post(
                path + "/messages",
                headers=token,
                json={"content": "new question", "request_id": "during-rollback"},
            ).status_code
            == 409
        )
        executor = Rollbacks(store, provider)
        action = executor.claim()
        assert executor.claim() is None
        executor.execute(action)
        provider.execute.assert_called_once()
        detail = client.get(path).json()["incident"]
        assert detail["status"] == "resolved"
        assert detail["action"]["status"] == "succeeded"
        assert client.get("/api/status").json()["incidents"] == {
            "active": 0,
            "attention": 0,
            "investigating": 0,
            "watching": 0,
        }
        # Closed incidents cannot start more mutations, even with a previous action ID.
        assert client.post(approve, headers=token).status_code == 409


def test_failure_and_restart_never_mark_recovery_or_replay(store):
    provider = cloud()
    provider.execute.side_effect = RuntimeError("provider unavailable")
    executor = Rollbacks(store, provider)
    incident = ready(store)
    proposal = executor.propose(incident, "rollback-first", "rollback")
    executor.approve(incident, proposal["id"], "operator")
    executor.execute(executor.claim())
    assert store.detail(incident)["incident"]["status"] == "active"
    assert store.detail(incident)["incident"]["action"]["status"] == "failed"
    assert store.summary()["attention"] == 1
    second = executor.propose(incident, "rollback-second", "rollback")
    executor.approve(incident, second["id"], "operator")
    executor.claim()
    executor.recover_interrupted()
    executor.recover_interrupted()
    assert executor.claim() is None
    assert store.detail(incident)["incident"]["action"]["status"] == "failed"
    provider.execute.assert_called_once()


def test_expired_approval_wrong_incident_and_concurrent_mutation_are_rejected(store):
    executor = Rollbacks(store, cloud())
    first, second = ready(store), ready(store)
    action = executor.propose(first, "rollback-first", "rollback")
    assert executor.propose(first, "rollback-first", "rollback")["id"] == action["id"]
    with pytest.raises(KeyError):
        executor.approve(second, action["id"], "operator")
    with store.engine.begin() as conn:
        conn.execute(
            update(actions)
            .where(actions.c.id == action["id"])
            .values(expires_at=now() - timedelta(seconds=1))
        )
    with pytest.raises(ValueError, match="expired"):
        executor.approve(first, action["id"], "operator")
    a = executor.propose(first, "rollback-fresh", "rollback")
    b = executor.propose(second, "rollback-other", "rollback")
    executor.approve(first, a["id"], "operator")
    with pytest.raises(ValueError, match="Another rollback"):
        executor.approve(second, b["id"], "operator")
    with store.engine.connect() as conn:
        assert (
            conn.execute(select(actions.c.status).where(actions.c.id == b["id"])).scalar()
            == "pending"
        )


def test_changed_service_and_target_fail_before_cloud_update():
    settings = Settings(
        _env_file=None, project_id="demo", shop_service="shop", rollback_revision="shop-good"
    )
    executor = RollbackCloud(settings)
    approved = cloud().plan()
    executor.plan = Mock(return_value={**approved, "etag": "changed"})
    executor.client = Mock()
    with pytest.raises(ValueError, match="service changed"):
        executor.execute(approved, Mock())
    executor.client.assert_not_called()
    with pytest.raises(ValueError, match="configuration changed"):
        executor.execute({**approved, "target": "shop-other"}, Mock())
    executor.client.assert_not_called()


def test_cloud_executor_updates_only_traffic_and_requires_all_probes(monkeypatch):
    from google.cloud import run_v2

    from sre_agent import rollback

    settings = Settings(
        _env_file=None, project_id="demo", shop_service="shop", rollback_revision="shop-good"
    )
    executor = RollbackCloud(settings)
    approved = cloud().plan()
    executor.plan = Mock(return_value=approved)
    executor.snapshot = Mock(return_value={**approved, "revision": "shop-good"})
    client = Mock()
    executor.client = Mock(return_value=client)
    response = Mock(status=200)
    response.read.return_value = b'{"status":"paid","version":"v1-healthy"}'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(rollback, "urlopen", Mock(return_value=response))
    monkeypatch.setattr(rollback, "fetch_id_token", Mock(return_value="test-token"))
    monkeypatch.setattr(rollback.time, "sleep", Mock())
    verifying = Mock()
    result = executor.execute(approved, verifying)
    assert len(result["checkout_checks"]) == 5
    verifying.assert_called_once()
    kwargs = client.update_service.call_args.kwargs
    # Actual protobuf parsing proves our Cloud Run request field names are accepted.
    request = run_v2.UpdateServiceRequest(kwargs["request"])
    assert list(request.update_mask.paths) == ["traffic"]
    assert request.service.etag == "version-1"
    assert request.service.traffic[0].revision == "shop-good"
    assert request.service.traffic[0].percent == 100
    response.read.return_value = b'{"status":"paid","version":"v2-broken"}'
    with pytest.raises(ValueError, match="not recovered"):
        executor.execute(approved, Mock())


def test_lost_worker_cannot_resurrect_failed_action(store):
    provider = cloud()
    executor = Rollbacks(store, provider)
    incident = ready(store)
    proposal = executor.propose(incident, "restart-race", "rollback")
    executor.approve(incident, proposal["id"], "operator")
    action = executor.claim()

    def interrupted(plan, verifying):
        executor.recover_interrupted()
        verifying()
        pytest.fail("Old worker continued after loss of ownership")

    provider.execute.side_effect = interrupted
    executor.execute(action)
    detail = store.detail(incident)["incident"]
    assert detail["status"] == "active"
    assert detail["action"]["status"] == "failed"
    assert store.summary()["attention"] == 1


def test_recovery_serializes_with_late_alert_and_cancels_queued_followup(store):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import event

    incident = store.create_incident("Checkout", "Investigate", source_id="race-recovery")
    store.finish(store.claim(), "Bad revision")
    executor = Rollbacks(store, cloud())
    proposal = executor.propose(incident, "recovery-race", "rollback")
    executor.approve(incident, proposal["id"], "operator")
    action = executor.claim()
    has_lock = threading.Event()
    release = threading.Event()
    attempted = threading.Event()

    def pause_intake(conn, cursor, statement, parameters, context, executemany):
        name = threading.current_thread().name
        if name.startswith("intake") and "SELECT runs.request_id" in statement:
            has_lock.set()
            assert release.wait(5)
        if (
            name.startswith("finish")
            and "FROM incidents" in statement
            and "FOR UPDATE" in statement
        ):
            attempted.set()

    # Pause intake after it owns the incident row, before writing the queued follow-up.
    def pause_after_lock(conn, cursor, statement, parameters, context, executemany):
        if threading.current_thread().name.startswith("intake") and "FOR UPDATE" in statement:
            has_lock.set()
            assert release.wait(5)

    event.listen(store.engine, "before_cursor_execute", pause_intake)
    event.listen(store.engine, "after_cursor_execute", pause_after_lock)
    try:
        with (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="intake") as pool,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="finish") as finisher,
        ):
            arriving = pool.submit(
                store.create_incident,
                "Checkout",
                "Alert closed",
                "monitoring",
                "race-recovery",
                "late-notification",
            )
            assert has_lock.wait(5)
            finishing = finisher.submit(executor.execute, action)
            try:
                assert attempted.wait(5)
                assert not finishing.done()
            finally:
                release.set()
            arriving.result(timeout=5)
            finishing.result(timeout=5)
    finally:
        release.set()
        event.remove(store.engine, "before_cursor_execute", pause_intake)
        event.remove(store.engine, "after_cursor_execute", pause_after_lock)
    assert store.detail(incident)["incident"]["status"] == "resolved"
    assert store.claim() is None


def test_deny_preserves_incident_and_never_queues_mutation(store):
    provider = cloud()
    executor = Rollbacks(store, provider)
    incident = ready(store)
    proposal = executor.propose(incident, "deny-me", "rollback")
    executor.deny(incident, proposal["id"], "operator")
    executor.deny(incident, proposal["id"], "operator")
    assert executor.claim() is None
    provider.execute.assert_not_called()
    detail = store.detail(incident)
    assert detail["incident"]["status"] == "active"
    assert detail["incident"]["action"]["status"] == "denied"
    assert sum(e["kind"] == "rollback_denied" for e in detail["events"]) == 1
    with pytest.raises(ValueError, match="expired or was replaced"):
        executor.approve(incident, proposal["id"], "operator")
    assert store.summary()["attention"] == 1


def test_deny_api_requires_csrf_and_rejects_another_incident(store):
    provider = cloud()
    incident, other = ready(store), ready(store)
    proposal = Rollbacks(store, provider).propose(incident, "deny-api", "rollback")
    app = create_app(Settings(_env_file=None), store=store, start_worker=False)
    with TestClient(app) as client:
        headers = {"x-csrf-token": client.get("/api/status").json()["csrf_token"]}
        path = f"/api/incidents/{incident}/actions/{proposal['id']}/deny"
        assert client.post(path).status_code == 403
        assert (
            client.post(
                f"/api/incidents/{other}/actions/{proposal['id']}/deny", headers=headers
            ).status_code
            == 404
        )
        assert client.post(path, headers=headers).json() == {"status": "denied"}
