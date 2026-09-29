"""Integration checks use isolated schemas on real local Postgres, never SQLite."""

import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from sre_agent.config import Settings
from sre_agent.main import create_app
from sre_agent.store import Store
from sre_agent.subscriber import Subscriber, parse_alert


@pytest.fixture
def store():
    url = make_url(
        os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql+psycopg://sre_demo:local-demo-only@127.0.0.1:55432/sre_demo",
        )
    )
    schema = "test_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    instance = Store(url.update_query_dict({"options": f"-csearch_path={schema}"}))
    instance.initialize()
    try:
        yield instance
    finally:
        instance.engine.dispose()
        with admin.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def test_alert_redelivery_and_chat_idempotence(store):
    args = dict(
        title="Errors",
        question="Investigate",
        source="monitoring",
        source_id="alert-123",
        request_id="pubsub:message-1",
    )
    incident = store.create_incident(**args)
    assert store.create_incident(**args) == incident
    assert len(store.detail(incident)["messages"]) == 1
    run = store.claim()
    assert run is not None
    assert store.claim() is None
    store.finish(run, "The new revision has errors")
    run_id = store.enqueue(incident, "Show evidence", "chat-request-1")
    assert store.enqueue(incident, "Show evidence", "chat-request-1") == run_id
    with pytest.raises(ValueError, match="another message"):
        store.enqueue(incident, "Different question", "chat-request-1")
    assert [m["content"] for m in store.detail(incident)["messages"]] == [
        "Investigate",
        "The new revision has errors",
        "Show evidence",
    ]


def test_close_requires_finished_runs_and_records_human_provenance(store):
    incident = store.create_incident("Errors", "Investigate", source_id="alert-123")
    with pytest.raises(ValueError, match="finish"):
        store.close(incident, "Fixed")
    run = store.claim()
    with pytest.raises(ValueError, match="finish"):
        store.close(incident, "Fixed")
    store.finish(run, "Likely bad deployment")
    store.close(incident, "Operator restored v1 and verified requests")
    store.close(incident, "Duplicate close")
    (lesson,) = store.recent_lessons()
    assert lesson["incident_id"] == incident
    assert lesson["content"] == (
        f"Human resolution for INC-{incident:03d}: Operator restored v1 and verified requests"
    )
    assert store.detail(incident)["events"][-1]["data"]["actor"] == "human"
    with pytest.raises(ValueError, match="closed"):
        store.enqueue(incident, "Retry", "request-after-close")
    assert (
        store.create_incident(
            "Late alert", "Investigate again", source_id="alert-123", request_id="late-delivery"
        )
        == incident
    )
    assert store.claim() is None
    assert store.detail(incident)["incident"]["status"] == "resolved"


def test_restart_marks_only_running_work_failed_without_duplicate_messages(store):
    first = store.create_incident("Running", "Investigate")
    store.claim()
    second = store.create_incident("Queued", "Investigate")
    store.recover_interrupted()
    store.recover_interrupted()
    assert store.detail(first)["incident"]["run_status"] == "failed"
    assert len(store.detail(first)["messages"]) == 2
    assert store.detail(second)["incident"]["run_status"] == "queued"
    assert store.claim()["incident_id"] == second


def test_api_rejects_cross_origin_and_missing_token_and_retains_context(store):
    app = create_app(Settings(_env_file=None, claude_model=""), store=store, start_worker=False)
    with TestClient(app) as client:
        status = client.get("/api/status")
        assert status.json()["configured"] is False
        headers = {"x-csrf-token": status.json()["csrf_token"]}
        body = {"question": "Why is checkout broken?"}
        assert client.post("/api/incidents", json=body).status_code == 403
        assert (
            client.post(
                "/api/incidents",
                json=body,
                headers={
                    **headers,
                    "origin": "https://attacker.example",
                },
            ).status_code
            == 403
        )
        assert client.get("/api/status", headers={"host": "attacker.example"}).status_code == 400
        response = client.post("/api/incidents", json=body, headers=headers)
        assert response.status_code == 201
        incident = response.json()["id"]
        assert (
            client.post(
                f"/api/incidents/{incident}/close", json={"notes": "Fixed"}, headers=headers
            ).status_code
            == 409
        )
        response = client.post(
            f"/api/incidents/{incident}/messages",
            headers=headers,
            json={"content": "What changed?", "request_id": "request-123"},
        )
        assert response.status_code == 202
        detail = client.get(f"/api/incidents/{incident}").json()
        assert [m["content"] for m in detail["messages"]] == [
            "Why is checkout broken?",
            "What changed?",
        ]
        assert client.get("/api/incidents/999999").status_code == 404


def alert_payload():
    return {
        "incident": {
            "incident_id": "123",
            "state": "open",
            "resource": {
                "labels": {"project_id": "project", "service_name": "shop"},
            },
        }
    }


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"incident": None},
        {"incident": {"incident_id": "123", "resource": None}},
        {"incident": {"incident_id": "123", "resource": {"labels": []}}},
    ],
)
def test_parser_rejects_invalid_structure(payload):
    with pytest.raises(ValueError):
        parse_alert(json.dumps(payload), "project", "shop")


def test_parser_rejects_out_of_scope_and_oversized_alerts():
    payload = alert_payload()
    assert parse_alert(json.dumps(payload), "project", "shop") == payload
    with pytest.raises(ValueError):
        parse_alert(json.dumps(payload), "other-project", "shop")
    with pytest.raises(ValueError):
        parse_alert("x" * 128_001, "project", "shop")


def test_subscriber_acks_only_after_durable_intake(store):
    from unittest.mock import Mock

    subscriber = Subscriber(
        Settings(_env_file=None, project_id="project", shop_service="shop"), store
    )
    message = Mock(data=json.dumps(alert_payload()), message_id="message-123")
    subscriber.receive(message)
    subscriber.receive(message)
    assert message.ack.call_count == 2
    message.nack.assert_not_called()
    assert len(store.list_incidents()) == 1
    assert len(store.detail(store.list_incidents()[0]["id"])["messages"]) == 1
    subscriber.store = Mock()
    subscriber.store.create_incident.side_effect = RuntimeError("DB unavailable")
    failed = Mock(data=json.dumps(alert_payload()), message_id="message-456")
    subscriber.receive(failed)
    failed.nack.assert_called_once()
    failed.ack.assert_not_called()


def test_concurrent_alert_waits_for_human_close_and_does_not_reopen(store):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import event

    incident = store.create_incident("Errors", "Investigate", source_id="race-alert")
    store.finish(store.claim(), "Diagnosis complete")
    close_has_lock = threading.Event()
    intake_attempted_lock = threading.Event()
    permit_close = threading.Event()

    def pause_close(conn, cursor, statement, parameters, context, executemany):
        thread = threading.current_thread().name
        if thread.startswith("closer") and "SELECT runs.id" in statement:
            close_has_lock.set()
            assert permit_close.wait(5), "Test did not release closing transaction"
        if (
            thread.startswith("intake")
            and "FROM incidents" in statement
            and "FOR UPDATE" in statement
        ):
            intake_attempted_lock.set()

    event.listen(store.engine, "before_cursor_execute", pause_close)
    try:
        with (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="closer") as closer,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="intake") as intake,
        ):
            closing = closer.submit(store.close, incident, "Human verified recovery")
            try:
                assert close_has_lock.wait(5), "Close did not acquire its incident lock"
                arriving = intake.submit(
                    store.create_incident,
                    "Late alert",
                    "Reinvestigate",
                    source_id="race-alert",
                    request_id="race-delivery",
                )
                assert intake_attempted_lock.wait(5), "Intake did not lock the incident row"
                assert not arriving.done()
            finally:
                permit_close.set()
            closing.result(timeout=5)
            assert arriving.result(timeout=5) == incident
    finally:
        permit_close.set()
        event.remove(store.engine, "before_cursor_execute", pause_close)
    assert store.detail(incident)["incident"]["status"] == "resolved"
    assert store.claim() is None
    assert len(store.recent_lessons()) == 1
