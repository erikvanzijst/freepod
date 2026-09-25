from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    artifacts,
    builds,
    users,
    products,
    deployments,
    hostnames,
    plans,
    registry,
    releases,
    ssh,
    ssh_keys,
    usage,
    subscriptions,
    vars,
    webhooks,
)
from app.api.util import register_exception_handlers
from app.db import get_session
from app.logging_config import configure_logging
from app.config import get_settings
from app.services.var_crypto import verify_keyring

configure_logging(level="DEBUG")

_settings = get_settings()


def _init_static_dir() -> None:
    (_settings.static_path / "icons").mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Refuse to serve when the var keyring cannot cover what is stored.

    The session is resolved through the app's own dependency, overrides
    included, so this verifies the database the process will actually serve
    rather than whatever `CAELUS_DATABASE_URL` happens to name.
    """
    provider = app.dependency_overrides.get(get_session, get_session)
    sessions = provider()
    try:
        verify_keyring(next(sessions))
    finally:
        sessions.close()
    yield


app = FastAPI(
    title="Freepod",
    description="Service for provisioning user-owned webapp instances on cloud infrastructure",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=_lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "https://app.deprutser.be"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Redirect root URL to Swagger UI docs."""
    return RedirectResponse(url="/api/docs")


@app.get("/docs", include_in_schema=False)
def redirect_to_docs() -> RedirectResponse:
    """Redirect /docs to /api/docs for backwards compatibility."""
    return RedirectResponse(url="/api/docs")


app.include_router(users.me_router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(deployments.router, prefix="/api")
app.include_router(releases.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(hostnames.router, prefix="/api")
app.include_router(plans.router, prefix="/api")
app.include_router(subscriptions.router, prefix="/api")
app.include_router(webhooks.router, prefix="/api")
app.include_router(artifacts.router, prefix="/api")
app.include_router(builds.router, prefix="/api")
app.include_router(vars.router, prefix="/api")
app.include_router(ssh_keys.router, prefix="/api")
app.include_router(usage.router, prefix="/api")
app.include_router(usage.admin_router, prefix="/api")
app.include_router(ssh.router, prefix="/api")
app.include_router(registry.router, prefix="/api")

_init_static_dir()
app.mount("/api/static", StaticFiles(directory=str(_settings.static_path)), name="static")

register_exception_handlers(app)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="info", reload=True)
