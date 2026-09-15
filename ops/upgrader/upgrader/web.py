"""The dashboard (D13, product-upgrade-dashboard)."""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .config import Settings
from .db import Run, make_sessionmaker, now
from .github import App, PullRequests
from .scheduler import Scheduler

log = logging.getLogger(__name__)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
IFRAMED = ("body.md", "change.patch")


def duration(start, end) -> str:
    if not start:
        return ""
    seconds = int(((end or now()) - start).total_seconds())
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m" if seconds >= 3600 else f"{seconds // 60}m{seconds % 60:02d}s"


templates.env.globals["duration"] = duration


def create_app(Session: sessionmaker, store, scheduler: Scheduler, prs: PullRequests,
               password: str | None, lifespan=None) -> FastAPI:
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    basic = HTTPBasic(auto_error=False)

    def authenticated(credentials: HTTPBasicCredentials | None = Depends(basic)) -> None:
        if not (password and credentials
                and hmac.compare_digest(credentials.password.encode(), password.encode())):
            raise HTTPException(401, headers={"WWW-Authenticate": 'Basic realm="upgrader"'})

    def choices() -> list[str]:
        with Session() as session:
            latest = session.scalars(
                select(Run).where(Run.scope.is_(None)).order_by(Run.id.desc()).limit(1)
            ).first()
            return [p.slug for p in latest.products] if latest else []

    def progress_context() -> dict:
        with Session() as session:
            run = session.scalars(
                select(Run).where(Run.finished_at.is_(None)).order_by(Run.id.desc()).limit(1)
            ).first()
            return {"run": run, "active": scheduler.active()}

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz():
        return "ok"

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(authenticated)])
    def index(request: Request, message: str | None = None):
        with Session() as session:
            runs = session.scalars(select(Run).order_by(Run.id.desc()).limit(200)).all()
        return templates.TemplateResponse(request, "index.html", {
            "runs": runs, "choices": choices(), "message": message, **progress_context()})

    @app.get("/progress", response_class=HTMLResponse, dependencies=[Depends(authenticated)])
    def progress(request: Request):
        return templates.TemplateResponse(request, "_progress.html", progress_context())

    @app.post("/runs", dependencies=[Depends(authenticated)])
    def start(request: Request, product: str = Form("")):
        scope = product or None
        if scope and scope not in choices():
            raise HTTPException(400, f"{scope} is not a product the last catalog run covered")
        if not scheduler.request(scope):
            return templates.TemplateResponse(request, "index.html", {
                "runs": [], "choices": choices(), **progress_context(),
                "message": "A run is already in progress, so this request was not started.",
            }, status_code=409)
        what = f"a run of {scope}" if scope else "a run of the whole catalog"
        return RedirectResponse(f"/?message=Started {what}.", status_code=303)

    @app.get("/runs/{run_id}", response_class=HTMLResponse, dependencies=[Depends(authenticated)])
    def run_page(request: Request, run_id: int):
        with Session() as session:
            run = session.get(Run, run_id)
        if not run:
            raise HTTPException(404)
        products = []
        for p in run.products:
            prefix = f"runs/{run.id}/{p.slug}/"
            links = {name: store.url(prefix + name) for name in p.files}
            products.append({
                "row": p,
                "links": links,
                "iframes": {n: links[n] for n in IFRAMED if n in links},
                "pr_state": prs.state(p.pr_url) if p.pr_url else None,
            })
        return templates.TemplateResponse(request, "run.html", {"run": run, "products": products})

    return app


def build() -> FastAPI:
    """The service as uvicorn runs it: `uvicorn --factory upgrader.web:build` (D1)."""
    from . import runner
    from .db import close_interrupted
    from .store import S3Store

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    Session = make_sessionmaker()
    store = S3Store()
    deps = runner.Deps(Session=Session, store=store)
    scheduler = Scheduler(lambda trigger, scope: runner.execute_run(deps, trigger, scope))
    try:
        app_client = App(settings.github_app_id, settings.github_app_private_key) \
            if settings.github_app_id and settings.github_app_private_key else None
    except ValueError:
        log.exception("GitHub App is misconfigured; PR states will be read anonymously")
        app_client = None

    @asynccontextmanager
    async def lifespan(_):
        close_interrupted(Session)
        scheduler.start()
        yield
        scheduler.stop.set()

    return create_app(Session, store, scheduler, PullRequests(app_client), settings.dashboard_password,
                      lifespan=lifespan)
