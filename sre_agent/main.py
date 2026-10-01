import logging
import secrets
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from sre_agent.config import ROOT, Settings
from sre_agent.deployment_watch import DeploymentCloud, DeploymentWatches, watch_request
from sre_agent.rollback import RollbackCloud, Rollbacks, rollback_request
from sre_agent.runner import AgentRunner
from sre_agent.store import Store
from sre_agent.subscriber import Subscriber
from sre_agent.worker import Worker

logging.basicConfig(level=logging.INFO)


class NewIncident(BaseModel):
    title: str = Field(default="Production investigation", min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=8, max_length=100)


class ChatMessage(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(min_length=8, max_length=100)


class CloseIncident(BaseModel):
    notes: str = Field(min_length=1, max_length=2000)


def create_app(
    settings=None,
    store=None,
    runner=None,
    start_worker=True,
    rollback_cloud=None,
    deployment_cloud=None,
):
    settings = settings or Settings()
    store = store or Store(settings.database_url)
    csrf = secrets.token_urlsafe(32)
    rollbacks = Rollbacks(store, rollback_cloud or RollbackCloud(settings))
    worker = Worker(store, runner or AgentRunner(settings, store), rollbacks)
    watches = DeploymentWatches(store, deployment_cloud or DeploymentCloud(settings))
    subscriber = Subscriber(settings, store)
    worker_enabled = start_worker and bool(settings.claude_model)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        if start_worker:
            watches.start()
        if worker_enabled:
            worker.start()
        if settings.subscriber_enabled:
            subscriber.start()
        yield
        subscriber.stop()
        if start_worker:
            watches.stop()
        if worker_enabled:
            worker.stop()
        store.engine.dispose()

    app = FastAPI(title="On-call desk", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.middleware("http")
    async def request_security(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if (
                origin
                and origin != str(request.base_url).rstrip("/")
                and origin not in settings.allowed_origins
            ):
                return JSONResponse(
                    {"detail": "Cross-origin requests are not allowed"}, status_code=403
                )
            if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), csrf):
                return JSONResponse({"detail": "Missing or invalid session token"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        return response

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/api/status")
    def status():
        return {
            "incidents": store.summary(),
            "project": settings.project_id,
            "service": settings.shop_service,
            "region": settings.region,
            "agent_provider": settings.agent_provider,
            "model": settings.claude_model,
            "subscriber_enabled": settings.subscriber_enabled,
            "subscriber_error": subscriber.error,
            "worker_busy": worker.busy,
            "worker_error": worker.error,
            "watcher_error": watches.error,
            "deployment_watch_enabled": start_worker,
            "csrf_token": csrf,
            "configured": bool(settings.claude_model),
            "mode": "approved-rollback" if settings.rollback_revision else "read-only",
            "rollback_enabled": bool(settings.rollback_revision),
        }

    @app.get("/api/incidents")
    def list_incidents():
        return store.list_incidents()

    @app.get("/api/incidents/{incident_id}")
    def detail(incident_id: int):
        try:
            return store.detail(incident_id)
        except KeyError:
            raise HTTPException(404, "Incident not found") from None

    @app.post("/api/incidents", status_code=201)
    def new_incident(body: NewIncident):
        if not body.question.strip():
            raise HTTPException(422, "Enter a question")
        try:
            command = watch_request(body.question)
            if command:
                if command.get("stop"):
                    raise ValueError("Open the conversation containing the watch to stop it.")
                watch = watches.create(None, body.request_id, body.question, command)
                return {"id": watch["incident_id"], "watch": watch}
            return {
                "id": store.create_incident(body.title, body.question, request_id=body.request_id)
            }
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/incidents/{incident_id}/messages", status_code=202)
    def message(incident_id: int, body: ChatMessage):
        if not body.content.strip():
            raise HTTPException(422, "Enter a message")
        try:
            command = watch_request(body.content)
            if command:
                if command.get("stop"):
                    return watches.cancel(incident_id, body.content)
                return {
                    "watch": watches.create(incident_id, body.request_id, body.content, command)
                }
            if rollback_request(body.content):
                if not settings.rollback_revision:
                    raise ValueError("Rollback is not configured for this service.")
                return {"action": rollbacks.propose(incident_id, body.request_id, body.content)}
            return {"run_id": store.enqueue(incident_id, body.content, body.request_id)}
        except KeyError:
            raise HTTPException(404, "Incident not found") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/incidents/{incident_id}/actions/{action_id}/approve", status_code=202)
    def approve(incident_id: int, action_id: str, request: Request):
        if not settings.rollback_revision or not worker_enabled:
            raise HTTPException(409, "Rollback executor is not enabled")
        try:
            actor = request.headers.get("x-goog-authenticated-user-email", "authenticated operator")
            rollbacks.approve(incident_id, action_id, actor)
            return {"status": "approved"}
        except KeyError:
            raise HTTPException(404, "Rollback proposal not found") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/incidents/{incident_id}/actions/{action_id}/deny")
    def deny(incident_id: int, action_id: str, request: Request):
        try:
            actor = request.headers.get("x-goog-authenticated-user-email", "authenticated operator")
            rollbacks.deny(incident_id, action_id, actor)
            return {"status": "denied"}
        except KeyError:
            raise HTTPException(404, "Rollback proposal not found") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/incidents/{incident_id}/watch/stop")
    def stop_watch(incident_id: int):
        try:
            return watches.cancel(incident_id)
        except KeyError:
            raise HTTPException(404, "Incident not found") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/incidents/{incident_id}/close")
    def close(incident_id: int, body: CloseIncident):
        if not body.notes.strip():
            raise HTTPException(422, "Enter resolution notes")
        try:
            store.close(incident_id, body.notes)
            return {"status": "resolved"}
        except KeyError:
            raise HTTPException(404, "Incident not found") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        logging.getLogger(__name__).exception("API failed", exc_info=exc)
        return JSONResponse(
            {"detail": "Backend unavailable. Check Postgres and server logs."}, status_code=503
        )

    dist = ROOT / "frontend/dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="console")
    return app


app = create_app()
