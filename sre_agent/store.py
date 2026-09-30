"""Postgres is the source of truth. Transactions never span an agent call."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    insert,
    select,
    update,
)

metadata = MetaData()


def now():
    return datetime.now(timezone.utc)


incidents = Table(
    "incidents",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source_id", String(300), unique=True),
    Column("title", String(200), nullable=False),
    Column("source", String(30), nullable=False),
    Column("status", String(20), nullable=False, default="active"),
    Column("created_at", DateTime(timezone=True), nullable=False, default=now),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=now),
)
messages = Table(
    "messages",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("incident_id", ForeignKey("incidents.id"), nullable=False),
    Column("role", String(20), nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), default=now, nullable=False),
)
runs = Table(
    "runs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("incident_id", ForeignKey("incidents.id"), nullable=False),
    Column("request_id", String(300), unique=True, nullable=False),
    Column("question", Text, nullable=False),
    Column("status", String(20), nullable=False, default="queued"),
    Column("created_at", DateTime(timezone=True), nullable=False, default=now),
)
events = Table(
    "events",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("incident_id", ForeignKey("incidents.id"), nullable=False),
    Column("kind", String(30), nullable=False),
    Column("tool_name", String(100)),
    Column("content", Text, nullable=False),
    Column("data", JSON, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), default=now, nullable=False),
)
evidence = Table(
    "evidence",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("incident_id", ForeignKey("incidents.id"), nullable=False),
    Column("title", String(200), nullable=False),
    Column("url", Text, nullable=False),
    Column("kind", String(30), nullable=False),
    Column("observed_at", DateTime(timezone=True), default=now, nullable=False),
    Column("data", JSON, nullable=False),
)
lessons = Table(
    "lessons",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("incident_id", ForeignKey("incidents.id"), nullable=False, unique=True),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), default=now, nullable=False),
)


class Store:
    def __init__(self, url):
        self.engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=0)

    def initialize(self):
        from sre_agent.rollback import actions  # noqa: F401

        metadata.create_all(self.engine)

    def _enqueue(self, conn, incident_id, content, request_id):
        existing = (
            conn.execute(select(runs).where(runs.c.request_id == request_id)).mappings().first()
        )
        if existing:
            if existing["incident_id"] != incident_id or existing["question"] != content:
                raise ValueError("Request ID was already used for another message")
            return existing["id"]
        run_id = str(uuid.uuid4())
        conn.execute(insert(messages).values(incident_id=incident_id, role="user", content=content))
        conn.execute(
            insert(runs).values(
                id=run_id, incident_id=incident_id, request_id=request_id, question=content
            )
        )
        conn.execute(
            update(incidents).where(incidents.c.id == incident_id).values(updated_at=now())
        )
        return run_id

    def create_incident(self, title, question, source="manual", source_id=None, request_id=None):
        # Serialize intake briefly, including concurrent duplicate Pub/Sub deliveries.
        with self.engine.begin() as conn:
            conn.exec_driver_sql("SELECT pg_advisory_xact_lock(734201)")
            duplicate = None
            if request_id:
                duplicate = (
                    conn.execute(select(runs).where(runs.c.request_id == request_id))
                    .mappings()
                    .first()
                )
            if duplicate:
                return duplicate["incident_id"]
            row = None
            if source_id:
                row = (
                    conn.execute(
                        select(incidents)
                        .where(incidents.c.source_id == source_id)
                        .with_for_update()
                    )
                    .mappings()
                    .first()
                )
            if row:
                incident_id = row["id"]
                # Human-closed records remain closed. Late notifications are recorded only.
                if row["status"] == "resolved":
                    conn.execute(
                        insert(events).values(
                            incident_id=incident_id,
                            kind="notification",
                            content="Notification received after incident closure",
                            data={"source_id": source_id},
                        )
                    )
                    return incident_id
            else:
                incident_id = conn.execute(
                    insert(incidents)
                    .values(
                        title=title[:200],
                        source=source,
                        source_id=source_id,
                    )
                    .returning(incidents.c.id)
                ).scalar_one()
            self._enqueue(conn, incident_id, question, request_id or str(uuid.uuid4()))
            return incident_id

    def enqueue(self, incident_id, content, request_id):
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    select(incidents).where(incidents.c.id == incident_id).with_for_update()
                )
                .mappings()
                .first()
            )
            if not row:
                raise KeyError(incident_id)
            if row["status"] == "resolved":
                raise ValueError("This incident is closed. Start a new investigation.")
            self.require_no_action(conn, incident_id)
            return self._enqueue(conn, incident_id, content, request_id)

    def action(self, conn, incident_id):
        from sre_agent.rollback import actions

        row = (
            conn.execute(
                select(actions)
                .where(actions.c.incident_id == incident_id)
                .order_by(actions.c.created_at.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def summary(self):
        from sre_agent.rollback import ACTIVE, actions

        queued = (
            select(runs.c.id)
            .where(runs.c.incident_id == incidents.c.id, runs.c.status.in_(["queued", "running"]))
            .exists()
        )
        changing = (
            select(actions.c.id)
            .where(actions.c.incident_id == incidents.c.id, actions.c.status.in_(ACTIVE))
            .exists()
        )
        with self.engine.connect() as conn:

            def count(*conditions):
                return conn.execute(
                    select(func.count())
                    .select_from(incidents)
                    .where(incidents.c.status != "resolved", *conditions)
                ).scalar_one()

            return {
                "active": count(),
                "attention": count(~queued, ~changing),
                "investigating": count(queued, ~changing),
            }

    def list_incidents(self):
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(incidents).order_by(incidents.c.id.desc()).limit(100)
            ).mappings()
            result = []
            for row in rows:
                item = dict(row)
                item["run_status"] = conn.execute(
                    select(runs.c.status)
                    .where(runs.c.incident_id == row["id"])
                    .order_by(runs.c.created_at.desc(), runs.c.id.desc())
                    .limit(1)
                ).scalar()
                item["action"] = self.action(conn, row["id"])
                result.append(item)
            return result

    def detail(self, incident_id):
        with self.engine.connect() as conn:
            row = (
                conn.execute(select(incidents).where(incidents.c.id == incident_id))
                .mappings()
                .first()
            )
            if not row:
                raise KeyError(incident_id)
            item = dict(row)
            item["run_status"] = conn.execute(
                select(runs.c.status)
                .where(runs.c.incident_id == incident_id)
                .order_by(runs.c.created_at.desc(), runs.c.id.desc())
                .limit(1)
            ).scalar()
            item["action"] = self.action(conn, incident_id)
            result = {"incident": item}
            for name, table in [("messages", messages), ("events", events), ("evidence", evidence)]:
                rows = list(
                    conn.execute(
                        select(table)
                        .where(table.c.incident_id == incident_id)
                        .order_by(table.c.id.desc())
                        .limit(200)
                    ).mappings()
                )
                result[name] = [dict(r) for r in reversed(rows)]
            return result

    def event(self, incident_id, kind, content, tool_name=None, data=None):
        with self.engine.begin() as conn:
            conn.execute(
                insert(events).values(
                    incident_id=incident_id,
                    kind=kind,
                    content=content,
                    tool_name=tool_name,
                    data=data or {},
                )
            )

    def save_evidence(self, incident_id, title, url, kind, data):
        with self.engine.begin() as conn:
            return conn.execute(
                insert(evidence)
                .values(incident_id=incident_id, title=title, url=url, kind=kind, data=data)
                .returning(evidence.c.id)
            ).scalar_one()

    def claim(self):
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    select(runs)
                    .where(runs.c.status == "queued")
                    .order_by(runs.c.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if row:
                conn.execute(update(runs).where(runs.c.id == row["id"]).values(status="running"))
                return dict(row)

    def finish(self, run, content, failed=False):
        with self.engine.begin() as conn:
            conn.execute(
                insert(messages).values(
                    incident_id=run["incident_id"], role="assistant", content=content
                )
            )
            conn.execute(
                update(runs)
                .where(runs.c.id == run["id"])
                .values(status="failed" if failed else "completed")
            )
            conn.execute(
                update(incidents)
                .where(incidents.c.id == run["incident_id"])
                .values(updated_at=now())
            )

    def recover_interrupted(self):
        with self.engine.begin() as conn:
            interrupted = (
                conn.execute(select(runs).where(runs.c.status == "running")).mappings().all()
            )
            for run in interrupted:
                conn.execute(
                    insert(messages).values(
                        incident_id=run["incident_id"],
                        role="assistant",
                        content="Investigation interrupted by restart. Send a message to retry.",
                    )
                )
            conn.execute(update(runs).where(runs.c.status == "running").values(status="failed"))

    def close(self, incident_id, notes):
        with self.engine.begin() as conn:
            # Same short lock used by intake; worker can still finish an already claimed run.
            row = (
                conn.execute(
                    select(incidents).where(incidents.c.id == incident_id).with_for_update()
                )
                .mappings()
                .first()
            )
            if not row:
                raise KeyError(incident_id)
            active = conn.execute(
                select(runs.c.id).where(
                    runs.c.incident_id == incident_id, runs.c.status.in_(["queued", "running"])
                )
            ).first()
            if active:
                raise ValueError("Wait for the investigation to finish before closing.")
            self.require_no_action(conn, incident_id)
            if row["status"] == "resolved":
                return
            conn.execute(
                update(incidents)
                .where(incidents.c.id == incident_id)
                .values(status="resolved", updated_at=now())
            )
            conn.execute(
                insert(lessons).values(
                    incident_id=incident_id,
                    content=f"Human resolution for INC-{incident_id:03d}: {notes}",
                )
            )
            conn.execute(
                insert(events).values(
                    incident_id=incident_id, kind="closed", content=notes, data={"actor": "human"}
                )
            )

    def require_no_action(self, conn, incident_id):
        from sre_agent.rollback import ACTIVE, actions

        if conn.execute(
            select(actions.c.id).where(
                actions.c.incident_id == incident_id, actions.c.status.in_(ACTIVE)
            )
        ).first():
            raise ValueError("Wait for rollback and recovery verification to finish.")

    def recent_lessons(self):
        with self.engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(lessons).order_by(lessons.c.id.desc()).limit(10)
                ).mappings()
            ]
