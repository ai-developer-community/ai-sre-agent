"""Human-approved, single-service rollback. The model cannot call this executor."""

import json
import logging
import re
import time
import uuid
from datetime import timedelta
from urllib.request import Request, urlopen

from google.auth.transport.requests import Request as AuthRequest
from google.cloud import run_v2
from google.oauth2.id_token import fetch_id_token
from sqlalchemy import insert, select, update

from sre_agent.store import (
    ROLLBACK_ACTIVE,
    actions,
    events,
    incidents,
    messages,
    now,
    require_no_watch,
    runs,
)

logger = logging.getLogger(__name__)


def rollback_request(content):
    # Only an explicit operator command takes this path. Logs and model output never do.
    return bool(
        re.fullmatch(
            r"(?:please\s+)?(?:rollback|roll back)(?:\s+(?:the\s+)?(?:change|deployment))?[.!]?",
            content.strip(),
            re.I,
        )
    )


class RollbackCloud:
    def __init__(self, settings):
        self.settings = settings
        self.name = (
            f"projects/{settings.project_id}/locations/{settings.region}"
            f"/services/{settings.shop_service}"
        )

    def client(self):
        return run_v2.ServicesClient()

    def snapshot(self):
        client = self.client()
        try:
            service = client.get_service(name=self.name, timeout=20)
            if service.reconciling or service.observed_generation != service.generation:
                raise ValueError("A deployment is still changing this service. Wait and try again.")
            traffic = [t for t in service.traffic_statuses if t.percent]
            if len(traffic) != 1 or traffic[0].percent != 100 or not traffic[0].revision:
                raise ValueError("Rollback requires one explicit serving revision at 100% traffic.")
            return {
                "service": self.name,
                "revision": traffic[0].revision.rsplit("/", 1)[-1],
                "etag": service.etag,
                "url": service.uri,
            }
        finally:
            client.transport.close()

    def plan(self):
        target = self.settings.rollback_revision
        if not target or not target.startswith(self.settings.shop_service + "-"):
            raise ValueError("No verified rollback revision is configured for this demo.")
        current = self.snapshot()
        client = run_v2.RevisionsClient()
        try:
            revision = client.get_revision(name=f"{self.name}/revisions/{target}", timeout=20)
            env = {v.name: v.value for v in revision.containers[0].env}
            if env.get("APP_VERSION") != "v1-healthy" or env.get("FAIL_RATE") != "0":
                raise ValueError("The configured target is not the verified healthy demo revision.")
        finally:
            client.transport.close()
        if current["revision"] == target:
            raise ValueError(
                "The healthy revision already serves all traffic. Ask for fresh evidence."
            )
        return {**current, "target": target}

    def execute(self, plan, verifying):
        if plan["service"] != self.name or plan["target"] != self.settings.rollback_revision:
            raise ValueError("Rollback configuration changed. Request a new proposal.")
        current = self.plan()
        if any(current[k] != plan[k] for k in ("revision", "etag", "url", "target")):
            raise ValueError("The service changed since this proposal. Request a new rollback.")
        client = self.client()
        try:
            operation = client.update_service(
                request={
                    "service": {
                        "name": self.name,
                        "etag": plan["etag"],
                        "traffic": [
                            {
                                "type_": "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION",
                                "revision": plan["target"],
                                "percent": 100,
                            }
                        ],
                    },
                    "update_mask": {"paths": ["traffic"]},
                },
                retry=None,
                timeout=30,
            )
            operation.result(timeout=120)
        finally:
            client.transport.close()
        verifying()
        observations = []
        for index in range(5):
            if index:
                time.sleep(2)
            snapshot = self.snapshot()
            if snapshot["revision"] != plan["target"]:
                raise ValueError(
                    "Serving traffic differs from the approved target. Check Cloud Run."
                )
            token = fetch_id_token(AuthRequest(), snapshot["url"])
            request = Request(
                snapshot["url"] + "/checkout",
                data=b"{}",
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            )
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
                if (
                    response.status != 200
                    or payload.get("status") != "paid"
                    or payload.get("version") != "v1-healthy"
                ):
                    raise ValueError(
                        "Checkout has not recovered. The incident still needs attention."
                    )
                observations.append(
                    {
                        "at": now().isoformat(),
                        "status": response.status,
                        "version": payload["version"],
                        "revision": snapshot["revision"],
                    }
                )
        if self.snapshot()["revision"] != plan["target"]:
            raise ValueError("Traffic changed during verification. Recovery is not confirmed.")
        return {
            "checkout_checks": observations,
            "revision": plan["target"],
            "verified_at": now().isoformat(),
            "scope": "Five successful checkout probes and serving revision; alert metrics may lag.",
        }


class Rollbacks:
    def __init__(self, store, cloud):
        self.store, self.cloud = store, cloud

    def _lock_incident(self, conn, incident_id):
        conn.exec_driver_sql("SELECT pg_advisory_xact_lock(734203)")
        row = (
            conn.execute(select(incidents).where(incidents.c.id == incident_id).with_for_update())
            .mappings()
            .first()
        )
        if not row:
            raise KeyError(incident_id)
        if row["status"] == "resolved":
            raise ValueError("This incident is closed.")
        require_no_watch(conn, incident_id)
        if conn.execute(
            select(runs.c.id).where(
                runs.c.incident_id == incident_id, runs.c.status.in_(["queued", "running"])
            )
        ).first():
            raise ValueError("Wait for the investigation to finish before requesting rollback.")

    def propose(self, incident_id, request_id, content):
        # Read the cloud before the short transaction. Execution rechecks this exact snapshot.
        with self.store.engine.connect() as conn:
            old = (
                conn.execute(select(actions).where(actions.c.request_id == request_id))
                .mappings()
                .first()
            )
            if old:
                if old["incident_id"] != incident_id:
                    raise ValueError("Request ID belongs to another incident.")
                return dict(old)
        plan = self.cloud.plan()
        with self.store.engine.begin() as conn:
            self._lock_incident(conn, incident_id)
            duplicate = (
                conn.execute(select(actions).where(actions.c.request_id == request_id))
                .mappings()
                .first()
            )
            if duplicate:
                if duplicate["incident_id"] != incident_id:
                    raise ValueError("Request ID belongs to another incident.")
                return dict(duplicate)
            existing = (
                conn.execute(
                    select(actions).where(
                        actions.c.incident_id == incident_id,
                        actions.c.status.in_(["pending", *ROLLBACK_ACTIVE]),
                    )
                )
                .mappings()
                .first()
            )
            if existing and existing["status"] in ROLLBACK_ACTIVE:
                raise ValueError("Rollback is already in progress.")
            conn.execute(
                update(actions)
                .where(actions.c.incident_id == incident_id, actions.c.status == "pending")
                .values(status="superseded")
            )
            action = {
                "id": str(uuid.uuid4()),
                "incident_id": incident_id,
                "request_id": request_id,
                "status": "pending",
                "plan": plan,
                "created_at": now(),
                "expires_at": now() + timedelta(minutes=5),
            }
            conn.execute(insert(actions).values(**action))
            conn.execute(
                insert(messages).values(incident_id=incident_id, role="user", content=content)
            )
            conn.execute(
                insert(messages).values(
                    incident_id=incident_id,
                    role="assistant",
                    content=f"Ready to roll back **{plan['revision']}** to **{plan['target']}**. "
                    "Approve below. Checkout checks must pass before recovery is marked verified.",
                )
            )
            return action

    def approve(self, incident_id, action_id, actor):
        with self.store.engine.begin() as conn:
            self._lock_incident(conn, incident_id)
            row = (
                conn.execute(
                    select(actions)
                    .where(actions.c.id == action_id, actions.c.incident_id == incident_id)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if not row:
                raise KeyError(action_id)
            if row["status"] in (*ROLLBACK_ACTIVE, "succeeded"):
                return  # Retried approval never repeats an executed change.
            if row["status"] != "pending" or row["expires_at"] <= now():
                raise ValueError("This proposal expired or was replaced. Request a new rollback.")
            if conn.execute(
                select(actions.c.id).where(actions.c.status.in_(ROLLBACK_ACTIVE))
            ).first():
                raise ValueError("Another rollback is in progress. Wait for its verification.")
            conn.execute(
                update(actions)
                .where(actions.c.id == action_id)
                .values(status="approved", actor=actor)
            )
            conn.execute(
                insert(events).values(
                    incident_id=incident_id,
                    kind="rollback_approved",
                    content="Operator approved rollback and checkout verification",
                    data={"action_id": action_id, "actor": actor, "target": row["plan"]["target"]},
                )
            )

    def deny(self, incident_id, action_id, actor):
        with self.store.engine.begin() as conn:
            self._lock_incident(conn, incident_id)
            row = (
                conn.execute(
                    select(actions)
                    .where(actions.c.id == action_id, actions.c.incident_id == incident_id)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if not row:
                raise KeyError(action_id)
            if row["status"] == "denied":
                return
            if row["status"] != "pending":
                raise ValueError("This rollback is no longer awaiting a decision.")
            conn.execute(
                update(actions)
                .where(actions.c.id == action_id)
                .values(status="denied", actor=actor)
            )
            conn.execute(
                insert(messages).values(
                    incident_id=incident_id,
                    role="assistant",
                    content="Rollback declined. Traffic is unchanged; the incident remains open.",
                )
            )
            conn.execute(
                insert(events).values(
                    incident_id=incident_id,
                    kind="rollback_denied",
                    content="Operator declined rollback",
                    data={"action_id": action_id, "actor": actor},
                )
            )

    def claim(self):
        with self.store.engine.begin() as conn:
            row = (
                conn.execute(
                    select(actions)
                    .where(actions.c.status == "approved")
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if row:
                conn.execute(
                    update(actions).where(actions.c.id == row["id"]).values(status="running")
                )
                return dict(row)

    def recover_interrupted(self):
        with self.store.engine.begin() as conn:
            for row in conn.execute(
                select(actions).where(actions.c.status.in_(["running", "verifying"]))
            ).mappings():
                conn.execute(
                    update(actions)
                    .where(actions.c.id == row["id"])
                    .values(
                        status="failed",
                        result={"error": "Executor restarted. Inspect checkout before retrying."},
                    )
                )
                conn.execute(
                    insert(messages).values(
                        incident_id=row["incident_id"],
                        role="assistant",
                        content="Rollback interrupted. Inspect checkout before retrying.",
                    )
                )

    def execute(self, action):
        def verifying():
            with self.store.engine.begin() as conn:
                changed = conn.execute(
                    update(actions)
                    .where(actions.c.id == action["id"], actions.c.status == "running")
                    .values(status="verifying")
                ).rowcount
                if not changed:
                    raise ValueError("Executor ownership changed. Recovery is unverified.")
            self.store.event(
                action["incident_id"],
                "recovery_check",
                "Traffic updated. Checking five checkout requests.",
            )

        try:
            if action["expires_at"] <= now():
                raise ValueError("Approval expired before execution. Request a new rollback.")
            result = self.cloud.execute(action["plan"], verifying)
            status = "succeeded"
            message = (
                f"Recovery verified: five HTTP 200 checkout checks on **{result['revision']}**. "
                + result["scope"]
            )
        except Exception as exc:
            # Provider responses can contain sensitive details; keep full errors in server logs.
            logger.exception("Rollback failed")
            result = {
                "error": str(exc)
                if isinstance(exc, ValueError)
                else "Recovery unverified. Inspect Cloud Run and checkout before retrying."
            }
            status, message = "failed", result["error"]
        with self.store.engine.begin() as conn:
            # Match intake/approval lock ordering before cancelling queued notifications.
            conn.execute(
                select(incidents.c.id)
                .where(incidents.c.id == action["incident_id"])
                .with_for_update()
            )
            # A restart can have marked the operation uncertain. Never overwrite that verdict.
            changed = conn.execute(
                update(actions)
                .where(actions.c.id == action["id"], actions.c.status.in_(["running", "verifying"]))
                .values(status=status, result=result)
            ).rowcount
            if not changed:
                return
            conn.execute(
                insert(messages).values(
                    incident_id=action["incident_id"], role="assistant", content=message
                )
            )
            conn.execute(
                insert(events).values(
                    incident_id=action["incident_id"],
                    kind="rollback_" + status,
                    content=message,
                    data=result,
                )
            )
            if status == "succeeded":
                conn.execute(
                    update(runs)
                    .where(runs.c.incident_id == action["incident_id"], runs.c.status == "queued")
                    .values(status="cancelled")
                )
                conn.execute(
                    update(incidents)
                    .where(incidents.c.id == action["incident_id"])
                    .values(status="resolved", updated_at=now())
                )
