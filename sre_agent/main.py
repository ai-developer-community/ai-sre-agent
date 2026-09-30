import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from sre_agent.config import ROOT, Settings
from sre_agent.runner import AgentRunner
from sre_agent.store import Store
from sre_agent.subscriber import Subscriber
from sre_agent.worker import Worker

logging.basicConfig(level=logging.INFO)


class NewIncident(BaseModel):
    title: str = Field(default="Production investigation", min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=4000)


class ChatMessage(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(min_length=8, max_length=100)


class CloseIncident(BaseModel):
    notes: str = Field(min_length=1, max_length=2000)


def create_app(settings=None, store=None, runner=None, start_worker=True):
    settings = settings or Settings()
    store = store or Store(settings.database_url)
    csrf = secrets.token_urlsafe(32)
    worker = Worker(store, runner or AgentRunner(settings, store))
    subscriber = Subscriber(settings, store)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        if start_worker:
            worker.start()
        if settings.subscriber_enabled:
            subscriber.start()
        yield
        subscriber.stop()
        if start_worker:
            worker.stop()
        store.engine.dispose()

    app = FastAPI(title="On-call desk", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse(
                    {"detail": "Cross-origin requests are not allowed"}, status_code=403
                )
            if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), csrf):
                return JSONResponse({"detail": "Missing or invalid session token"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        return response

    @app.get("/api/status")
    def status():
        return {
            "project": settings.project_id,
            "service": settings.shop_service,
            "region": settings.region,
            "agent_provider": settings.agent_provider,
            "model": settings.claude_model,
            "subscriber_enabled": settings.subscriber_enabled,
            "subscriber_error": subscriber.error,
            "worker_busy": worker.busy,
            "worker_error": worker.error,
            "csrf_token": csrf,
            "configured": bool(settings.claude_model),
            "mode": "read-only",
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
        return {"id": store.create_incident(body.title, body.question)}

    @app.post("/api/incidents/{incident_id}/messages", status_code=202)
    def message(incident_id: int, body: ChatMessage):
        if not body.content.strip():
            raise HTTPException(422, "Enter a message")
        try:
            return {"run_id": store.enqueue(incident_id, body.content, body.request_id)}
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
