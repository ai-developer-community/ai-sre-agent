"""Hosted console boundaries and rolling-deployment worker handover."""

import json
import threading
import time
import uuid
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from test_backend import store as store

from sre_agent.config import Settings
from sre_agent.main import create_app
from sre_agent.subscriber import parse_alert
from sre_agent.worker import Worker


def test_hosted_host_and_proxy_origin_boundaries(store):
    settings = Settings(
        _env_file=None,
        allowed_hosts=["agent.example.run.app"],
        allowed_origins=["http://localhost:8080"],
    )
    app = create_app(settings=settings, store=store, start_worker=False)
    with TestClient(app, base_url="https://agent.example.run.app") as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/healthz", headers={"host": "attacker.example"}).status_code == 400
        token = client.get("/api/status").json()["csrf_token"]
        for origin in ("http://localhost:8080", "https://agent.example.run.app"):
            response = client.post(
                "/api/incidents",
                headers={"origin": origin, "x-csrf-token": token},
                json={"question": "Investigate checkout"},
            )
            assert response.status_code == 201
        for origin in ("https://attacker.example", "http://localhost:8080.attacker.example"):
            response = client.post(
                "/api/incidents",
                headers={"origin": origin, "x-csrf-token": token},
                json={"question": "Investigate checkout"},
            )
            assert response.status_code == 403
        assert (
            client.post(
                "/api/incidents",
                headers={"origin": "http://localhost:8080"},
                json={"question": "Investigate checkout"},
            ).status_code
            == 403
        )


def test_alert_region_is_required_when_configured():
    payload = {
        "incident": {
            "incident_id": "region-test",
            "state": "open",
            "resource": {"labels": {"project_id": "project", "service_name": "shop"}},
        }
    }
    for region in (None, "us-central1"):
        payload["incident"]["resource"]["labels"]["location"] = region
        with pytest.raises(ValueError, match="region"):
            parse_alert(json.dumps(payload), "project", "shop", "europe-west2")
    payload["incident"]["resource"]["labels"]["location"] = "europe-west2"
    assert parse_alert(json.dumps(payload), "project", "shop", "europe-west2") == payload


def test_missing_model_preserves_queued_work_without_starting_worker(store, monkeypatch):
    start = Mock()
    monkeypatch.setattr(Worker, "start", start)
    app = create_app(settings=Settings(_env_file=None, claude_model=""), store=store)
    with TestClient(app) as client:
        status = client.get("/api/status").json()
        assert status["configured"] is False
        response = client.post(
            "/api/incidents",
            json={"question": "Pending model access"},
            headers={"x-csrf-token": status["csrf_token"]},
        )
        assert response.status_code == 201
        assert store.detail(response.json()["id"])["incident"]["run_status"] == "queued"
        start.assert_not_called()


def wait_until(condition, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    pytest.fail("Worker condition did not become true before timeout")


def isolate_worker_lock(store):
    # Advisory locks span schemas. Avoid competing with a real local demo worker.
    key = str(uuid.uuid4().int % 2_000_000_000)

    @event.listens_for(store.engine, "before_cursor_execute", retval=True)
    def unique_lock(connection, cursor, statement, parameters, context, executemany):
        return statement.replace("734202", key), parameters


def test_standby_worker_takes_over_after_previous_revision_releases_lock(store):
    isolate_worker_lock(store)
    completed = threading.Event()

    class Runner:
        async def run(self, run):
            completed.set()
            return "Evidence gathered"

    store.create_incident("Checkout", "Investigate")
    worker = Worker(store, Runner())
    with store.engine.connect() as previous:
        assert previous.exec_driver_sql("SELECT pg_try_advisory_lock(734202)").scalar()
        previous.commit()
        worker.start()
        try:
            wait_until(lambda: worker.error is not None)
            assert not completed.is_set()
            previous.exec_driver_sql("SELECT pg_advisory_unlock(734202)")
            previous.commit()
            assert completed.wait(5)
            wait_until(lambda: not worker.busy)
            assert worker.error is None
        finally:
            worker.stop()
    assert not worker.thread.is_alive()


def test_worker_retries_after_connection_failure(store, monkeypatch):
    isolate_worker_lock(store)
    recovered = threading.Event()
    connect = store.engine.connect
    attempts = 0

    def transient_failure():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("Temporary database outage")
        recovered.set()
        return connect()

    monkeypatch.setattr(store.engine, "connect", transient_failure)
    worker = Worker(store, Mock())
    worker.start()
    try:
        assert recovered.wait(5)
        wait_until(lambda: worker.error is None)
    finally:
        worker.stop()
    assert attempts >= 2
    assert not worker.thread.is_alive()
