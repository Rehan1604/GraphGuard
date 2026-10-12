import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.alerts.routes import router as alerts_router
from app.config import Settings, get_settings
from app.db import connect, init_db
from app.evaluation.routes import router as evaluation_router
from app.logging_config import setup_logging
from app.middleware import install_middleware
from app.rag.routes import router as rag_router
from app.realtime import EventHub
from app.routes import router
from app.simulation.routes import router as simulation_router
from app.simulation.service import Simulator

STATIC_DIR = Path(__file__).resolve().parent / "static"
log = logging.getLogger("graphguard")


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    server_time: datetime


def create_app(settings: Settings | None = None) -> FastAPI:
    explicit = settings

    def current() -> Settings:
        """An explicitly passed Settings wins; otherwise read the (cached) environment settings
        each time, so the module-level app follows get_settings() instead of freezing it at import."""
        return explicit or get_settings()

    settings = current()  # used for things fixed at construction time (docs, CORS)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = current()
        app.state.settings = settings
        setup_logging(settings.log_level, settings.log_format)
        settings.validate_for_environment()  # refuse to start on unsafe configuration
        log.info("starting GraphGuard", extra={"config": settings.summary()})
        init_db(settings.database_path)
        hub = EventHub()
        app.state.hub = hub
        app.state.simulator = Simulator(hub, lambda: current().database_path)
        yield
        await app.state.simulator.shutdown()
        log.info("GraphGuard stopped")

    docs = settings.docs_are_enabled
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    if explicit is not None:
        app.state.settings = explicit  # the default app reads get_settings() live instead

    # Added first, so it sits inside the CORS layer: CORS headers still reach error responses.
    install_middleware(app, settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    for r in (router, alerts_router, simulation_router, rag_router, evaluation_router):
        app.include_router(r)

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness: if this answers, the process is up. It checks nothing else."""
        return HealthResponse(
            status="ok", service=settings.app_name, version=settings.version,
            environment=settings.environment, server_time=datetime.now(timezone.utc),
        )

    @app.get("/api/ready")
    def ready() -> JSONResponse:
        """Readiness: can this instance actually do its job? Checks the database."""
        try:
            conn = connect(current().database_path)
            try:
                conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone()  # also proves the tables exist
            finally:
                conn.close()
        except Exception as exc:
            log.warning("readiness check failed: %s", type(exc).__name__)
            return JSONResponse({"status": "unavailable", "database": "error"}, status_code=503)
        return JSONResponse({"status": "ready", "database": "ok"})

    @app.get("/live", include_in_schema=False)
    def live_console() -> FileResponse:
        """A plain debugging page for watching the live stream."""
        return FileResponse(STATIC_DIR / "live.html")

    return app


app = create_app()
