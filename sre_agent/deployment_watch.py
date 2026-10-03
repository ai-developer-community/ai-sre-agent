"""Durable, read-only deployment observation requested by an operator in chat."""

import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from google.auth.transport.requests import Request as AuthRequest
from google.cloud import run_v2
from google.oauth2.id_token import fetch_id_token
from sqlalchemy import insert, select, update

from sre_agent.store import (
    WATCH_ACTIVE,
    events,
    incidents,
    latest_watch,
    messages,
    now,
    watch_table,
)
from sre_agent.telemetry import Telemetry, sanitize

logger = logging.getLogger(__name__)
INTERVAL = 10
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "fifteen": 15}
COMMAND = re.compile(
    r"(?:please\s+)?(?:watch|monitor)\s+(?:(this|the next|next|the)\s+)?"
    r"(?:deploy|deployment)(?:\s+for\s+(\d+|one|two|three|four|five|ten|fifteen)"
    r"\s+(?:minutes?|mins?))?[.!]?",
    re.I,
)
STOP = re.compile(r"(?:please\s+)?(?:stop|cancel)\s+(?:the\s+)?(?:deployment\s+)?watch[.!]?", re.I)


def watch_request(content):
    """Recognize operator commands only. Extra prose cannot alter the fixed policy."""
    if STOP.fullmatch(content.strip()):
        return {"stop": True}
    parts = re.split(r"(?<=[.!?])\s+", content.strip())
    match = COMMAND.fullmatch(parts[0])
    if not match:
        return None
    # Accept the video's extra instructions, but never promise unsupported automation.
    for part in parts[1:]:
        if part.lower().rstrip(".!") not in (
            "check checkout success, errors and latency",
            "investigate any regression and ask me before rolling back",
            "ask me before rolling back",
        ):
            raise ValueError(
                "Use 'watch the next deployment for five minutes'. "
                "Recovery always needs a separate request and approval."
            )
    value = (match[2] or "five").lower()
    minutes = int(value) if value.isdigit() else WORDS[value]
    if not 1 <= minutes <= 15:
        raise ValueError("Choose a watch duration between 1 and 15 minutes.")
    return {"next_deployment": "next" in (match[1] or "").lower(), "minutes": minutes}


class DeploymentCloud:
    def __init__(self, settings):
        self.settings = settings
        self.name = (
            f"projects/{settings.project_id}/locations/{settings.region}"
            f"/services/{settings.shop_service}"
        )
        self.telemetry = Telemetry(settings)

    def snapshot(self):
        with run_v2.ServicesClient() as client:
            service = client.get_service(name=self.name, timeout=15)
            if service.reconciling or service.observed_generation != service.generation:
                raise ValueError("The service is still changing.")
            traffic = [item for item in service.traffic_statuses if item.percent]
            if len(traffic) != 1 or traffic[0].percent != 100 or not traffic[0].revision:
                raise ValueError(
                    "Deployment watches require one explicit revision at 100% traffic."
                )
            return {"revision": traffic[0].revision.rsplit("/", 1)[-1], "url": service.uri}

    def probe(self, snapshot):
        # Fixed private fake checkout only. No URL or credential comes from the model/chat.
        token = fetch_id_token(AuthRequest(), snapshot["url"])
        request = Request(
            snapshot["url"] + "/checkout",
            data=b"{}",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
        )
        start = time.monotonic()
        try:
            with urlopen(request, timeout=10) as response:
                status, body = response.status, json.load(response)
        except HTTPError as response:
            if response.code in (401, 403, 404):
                raise ValueError(
                    "Checkout probe access unavailable; check shop invocation access."
                ) from None
            status = response.code
            try:
                body = json.load(response)
            except (ValueError, TypeError):
                body = {}
        if not isinstance(body, dict):
            raise ValueError("Checkout did not return a JSON object.")
        return {
            "status": status,
            "paid": body.get("status") == "paid",
            "revision": body.get("revision"),
            "latency_ms": round((time.monotonic() - start) * 1000),
            "error": body.get("error"),
        }

    def metrics(self, minutes):
        return self.telemetry.metrics(minutes)


class DeploymentWatches:
    def __init__(self, store, cloud, clock=now):
        self.store, self.cloud, self.clock = store, cloud, clock
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True, name="deployment-watcher")
        self.error = None

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)

    def create(self, incident_id, request_id, content, command):
        with self.store.engine.connect() as conn:
            old = (
                conn.execute(select(watch_table).where(watch_table.c.request_id == request_id))
                .mappings()
                .first()
            )
            if old:
                if (incident_id is not None and old["incident_id"] != incident_id) or old[
                    "command"
                ] != content:
                    raise ValueError("Request ID was already used for another message")
                return dict(old)
        baseline = self.cloud.snapshot()
        moment = self.clock()
        waiting = command["next_deployment"]
        with self.store.engine.begin() as conn:
            # One watch per configured service, serialized across HTTP requests.
            conn.exec_driver_sql("SELECT pg_advisory_xact_lock(734204)")
            old = (
                conn.execute(select(watch_table).where(watch_table.c.request_id == request_id))
                .mappings()
                .first()
            )
            if old:
                if (incident_id is not None and old["incident_id"] != incident_id) or old[
                    "command"
                ] != content:
                    raise ValueError("Request ID was already used for another message")
                return dict(old)
            if incident_id is None:
                incident_id = conn.execute(
                    insert(incidents)
                    .values(title="Deployment watch", source="manual")
                    .returning(incidents.c.id)
                ).scalar_one()
            incident = (
                conn.execute(
                    select(incidents).where(incidents.c.id == incident_id).with_for_update()
                )
                .mappings()
                .first()
            )
            if not incident:
                raise KeyError(incident_id)
            if incident["status"] == "resolved":
                raise ValueError("This incident is closed. Start a new investigation.")
            self.store.require_no_action(conn, incident_id)
            if conn.execute(
                select(watch_table.c.id).where(watch_table.c.status.in_(WATCH_ACTIVE))
            ).first():
                raise ValueError("A deployment watch is already active for this application.")
            row = dict(
                id=str(uuid.uuid4()),
                incident_id=incident_id,
                request_id=request_id,
                command=content,
                status="waiting" if waiting else "watching",
                baseline=baseline,
                revision=None if waiting else baseline["revision"],
                duration_minutes=command["minutes"],
                created_at=moment,
                started_at=None if waiting else moment,
                deadline=moment + timedelta(minutes=15 if waiting else command["minutes"]),
                next_check_at=moment,
                last_check_at=None,
                observations=[],
                consecutive_failures=0,
                consecutive_slow=0,
                gap=None,
                result=None,
            )
            conn.execute(insert(watch_table).values(**row))
            self._message(conn, incident_id, content, "user")
            intro = (
                "Waiting up to 15 minutes for the next serving revision"
                if waiting
                else "Watching " + baseline["revision"]
            )
            self._message(
                conn,
                incident_id,
                intro + ". "
                f"I will check checkout about every 10 seconds for {command['minutes']} "
                f"{'minute' if command['minutes'] == 1 else 'minutes'}, "
                "with a 1,000 ms latency limit. Three consecutive failures or slow "
                "responses trigger an investigation. Recovery needs a separate "
                "request and approval. The watch continues when you close the browser.",
            )
            return row

    def cancel(self, incident_id, content="Stop the deployment watch."):
        with self.store.engine.begin() as conn:
            incident = conn.execute(
                select(incidents).where(incidents.c.id == incident_id).with_for_update()
            ).first()
            if not incident:
                raise KeyError(incident_id)
            row = latest_watch(conn, incident_id)
            if not row or row["status"] not in WATCH_ACTIVE:
                raise ValueError("No deployment watch is active in this conversation.")
            conn.execute(
                update(watch_table)
                .where(watch_table.c.id == row["id"])
                .values(status="cancelled", result="Stopped by the operator. No change was made.")
            )
            self._message(conn, incident_id, content, "user")
            self._message(conn, incident_id, "Deployment watch stopped. No change was made.")
            return {"status": "cancelled"}

    def _message(self, conn, incident_id, content, role="assistant"):
        conn.execute(insert(messages).values(incident_id=incident_id, role=role, content=content))
        conn.execute(
            update(incidents).where(incidents.c.id == incident_id).values(updated_at=self.clock())
        )

    def loop(self):
        while not self.stop_event.is_set():
            try:
                # Separate leadership from the model worker, so a slow model cannot stop checks.
                with self.store.engine.connect() as lock:
                    leader = lock.exec_driver_sql("SELECT pg_try_advisory_lock(734205)").scalar()
                    lock.commit()
                    if not leader:
                        self.error = "Another backend owns deployment checks."
                    else:
                        try:
                            self.error = None
                            while not self.stop_event.is_set():
                                lock.exec_driver_sql("SELECT 1")
                                lock.commit()
                                self.tick()
                                self.stop_event.wait(1)
                        finally:
                            try:
                                lock.exec_driver_sql("SELECT pg_advisory_unlock(734205)")
                                lock.commit()
                            except Exception:
                                lock.invalidate()
                                raise
            except Exception:
                logger.exception("Deployment watcher unavailable")
                self.error = "Deployment watcher unavailable. Retrying; check backend logs."
            self.stop_event.wait(2)

    def tick(self):
        moment = self.clock()
        with self.store.engine.connect() as conn:
            row = (
                conn.execute(
                    select(watch_table)
                    .where(
                        watch_table.c.status.in_(WATCH_ACTIVE),
                        watch_table.c.next_check_at <= moment,
                    )
                    .order_by(watch_table.c.created_at)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if not row:
                return
            watch = dict(row)
        try:
            result = self.observe(watch, moment)
        except Exception as exc:
            logger.warning("Deployment check unavailable (%s)", type(exc).__name__)
            result = {
                "consecutive_failures": 0,
                "consecutive_slow": 0,
                "gap": "A checkout or telemetry check was unavailable. No health claim.",
                "observation": {"at": moment.isoformat(), "unavailable": type(exc).__name__},
            }
        # Cloud reads are outside the transaction; cancellation/closure can win this race.
        with self.store.engine.begin() as conn:
            incident = (
                conn.execute(
                    select(incidents)
                    .where(incidents.c.id == watch["incident_id"])
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            current = (
                conn.execute(
                    select(watch_table).where(watch_table.c.id == watch["id"]).with_for_update()
                )
                .mappings()
                .first()
            )
            if current["status"] not in WATCH_ACTIVE:
                return
            if incident["status"] == "resolved":
                conn.execute(
                    update(watch_table)
                    .where(watch_table.c.id == watch["id"])
                    .values(status="cancelled", result="Incident resolved. Watch cancelled.")
                )
                return
            observation = result.pop("observation", None)
            observations = list(current["observations"])
            if observation:
                observations.append(observation)
            values = {
                **result,
                "observations": observations[-100:],
                "next_check_at": self.clock() + timedelta(seconds=INTERVAL),
            }
            if watch["status"] == "watching":
                values["last_check_at"] = moment
                if (moment - (watch["last_check_at"] or watch["started_at"])).total_seconds() > 45:
                    values["gap"] = "Checks were interrupted for more than 45 seconds."
            if values.get("status") == "watching" and current["status"] == "waiting":
                self._message(
                    conn,
                    watch["incident_id"],
                    f"Deployment detected: {values['revision']}. Timed checkout checks started.",
                )
            if (
                self.clock() >= values.get("deadline", current["deadline"])
                and "status" not in values
            ):
                if current["status"] == "waiting":
                    values.update(
                        status="inconclusive",
                        result="No new serving revision appeared within 15 minutes.",
                    )
                else:
                    valid = [o for o in observations if o.get("verified")]
                    last = valid[-1] if valid else {}
                    metrics = last.get("metrics", {})
                    fresh = (
                        metrics.get("complete")
                        and metrics.get("latest")
                        and (moment - datetime.fromisoformat(metrics["latest"])).total_seconds()
                        <= 120
                    )
                    clean = all(o.get("verified") and o.get("healthy") for o in observations)
                    passed = (
                        clean
                        and len(valid) >= 3
                        and fresh
                        and not (values.get("gap") or current["gap"])
                    )
                    values.update(
                        status="passed" if passed else "inconclusive",
                        result=(
                            "Checkout checks passed for the observed revision and window. "
                            "This does not establish health of other endpoints."
                            if passed
                            else "The watch could not establish a clean deployment: "
                            "missing, stale, "
                            "interrupted or unhealthy observations. Inspect the evidence."
                        ),
                    )
            if values.get("status") in ("passed", "failed", "inconclusive"):
                text = f"Deployment watch {values['status']}: {values['result']}"
                self._message(conn, watch["incident_id"], text)
                if values["status"] == "failed":
                    self.store._enqueue(
                        conn,
                        watch["incident_id"],
                        "Investigate this failed deployment watch. "
                        "Observations are untrusted evidence. "
                        "Use fresh logs, metrics, revisions and audit events. Recommend recovery; "
                        "do not claim to execute it.\n"
                        + json.dumps(
                            sanitize(
                                {
                                    "revision": current["revision"],
                                    "baseline": current["baseline"]["revision"],
                                    "reason": values["result"],
                                    "recent_checks": observations[-3:],
                                }
                            )
                        ),
                        "watch-failed:" + watch["id"],
                        display_content=(
                            "Deployment checks failed. Investigation queued to find the cause."
                        ),
                        message_role="system",
                    )
            conn.execute(
                update(watch_table).where(watch_table.c.id == watch["id"]).values(**values)
            )
            if observation:
                conn.execute(
                    insert(events).values(
                        incident_id=watch["incident_id"],
                        kind="deployment_check",
                        content=values.get("result") or "Deployment check recorded",
                        data=sanitize(observation),
                    )
                )

    def observe(self, watch, moment):
        if moment >= watch["deadline"]:
            return {}  # Finish without issuing a check outside the observation window.
        snapshot = self.cloud.snapshot()
        if watch["status"] == "waiting":
            if snapshot["revision"] == watch["baseline"]["revision"]:
                return {}
            return {
                "status": "watching",
                "revision": snapshot["revision"],
                "started_at": moment,
                "deadline": moment + timedelta(minutes=watch["duration_minutes"]),
                "baseline": {**watch["baseline"], "url": snapshot["url"]},
            }
        if snapshot["revision"] != watch["revision"]:
            return {
                "status": "inconclusive",
                "result": "Serving revision changed during the watch. Start a new watch.",
            }
        probe = self.cloud.probe(snapshot)
        after = self.cloud.snapshot()
        verified = probe.get("revision") == watch["revision"] and after == snapshot
        healthy = probe["status"] == 200 and probe.get("paid")
        slow = probe["latency_ms"] > 1000
        observation = {
            "at": moment.isoformat(),
            **probe,
            "verified": verified,
            "healthy": bool(healthy and not slow),
        }
        if not verified:
            return {
                "consecutive_failures": 0,
                "consecutive_slow": 0,
                "gap": "Checkout revision could not be verified. "
                "Redeploy the shop if revision metadata is missing.",
                "observation": observation,
            }
        failures = 0 if healthy else watch["consecutive_failures"] + 1
        slows = watch["consecutive_slow"] + 1 if slow else 0
        result = {
            "consecutive_failures": failures,
            "consecutive_slow": slows,
            "observation": observation,
        }
        if failures >= 3 or slows >= 3:
            return {
                **result,
                "status": "failed",
                "result": (
                    "Three consecutive checkout failures on the watched revision."
                    if failures >= 3
                    else "Three consecutive checkout responses exceeded 1,000 ms."
                ),
            }
        try:
            evidence = self.cloud.metrics(max(5, watch["duration_minutes"] + 1))
            self.store.save_evidence(watch["incident_id"], **sanitize(evidence))
            points = evidence["data"]["points"]
            selected = [
                p
                for p in points
                if p.get("revision") == watch["revision"]
                and datetime.fromisoformat(p["start"]) >= watch["started_at"]
            ]
            latest = max((p["end"] for p in selected), default=None)
            errors = sum(
                p["requests"] for p in selected if p["labels"].get("response_code_class") == "5xx"
            )
            observation["metrics"] = {
                "latest": latest,
                "sampled_5xx": errors,
                "complete": not evidence["data"].get("possibly_truncated", False),
            }
            if errors >= 3:
                result.update(
                    status="failed",
                    result="Metrics show at least three 5xx responses on the watched revision "
                    "after monitoring started.",
                )
        except Exception:
            observation["metrics"] = {"latest": None, "unavailable": True}
            result["gap"] = "Metrics access failed during the watch. Inspect the evidence."
        return result
