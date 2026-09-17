"""The dashboard (D13, product-upgrade-dashboard)."""

from __future__ import annotations

import hmac
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.routing import APIRoute
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .cancel import Cancellation
from .config import Settings
from .db import ProductResult, Run, make_sessionmaker, now
from .github import App, PullRequests
from .live import Live
from .live import read as read_live
from .schedule import next_run
from .scheduler import Scheduler

log = logging.getLogger(__name__)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
TONES = {
    "opened": "good", "would_open": "good", "up_to_date": "calm", "skipped": "cool",
    "would_skip": "cool", "failed": "bad", "timed_out": "bad", "interrupted": "bad", "running": "live",
    "canceled": "cool",
}
FILE_LABELS = {
    "session.html": "Transcript", "session.jsonl": "Transcript (JSONL)", "stdout.txt": "Output",
    "result.json": "result.json", "body.md": "Description", "change.patch": "Patch",
}


def duration(start, end) -> str:
    if not start:
        return ""
    seconds = int(((end or now()) - start).total_seconds())
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m" if seconds >= 3600 else f"{seconds // 60}m{seconds % 60:02d}s"


def _span(seconds: int) -> str:
    if seconds < 60:
        return "moments"
    if seconds < 3600:
        return f"{seconds // 60} min"
    if seconds < 86400:
        return f"{seconds // 3600} h {seconds % 3600 // 60} min"
    return f"{seconds // 86400} d"


def ago(moment) -> str:
    return f"{_span(int((now() - moment).total_seconds()))} ago"


def until(moment) -> str:
    return f"in {_span(int((moment - now()).total_seconds()))}"


templates.env.globals.update(
    duration=duration, ago=ago, until=until,
    tone=lambda outcome: TONES.get(outcome, "calm"),
    label=lambda outcome: outcome.replace("_", " "),
    file_label=lambda name: FILE_LABELS.get(name, name),
)


class _HeadAllowed(APIRoute):
    """FastAPI, unlike Starlette's own Route, does not answer HEAD on a GET route."""

    def __init__(self, path, endpoint, *, methods=None, **kwargs):
        if methods and "GET" in methods:
            methods = [*methods, "HEAD"]
        super().__init__(path, endpoint, methods=methods, **kwargs)


def create_app(Session: sessionmaker, store, scheduler: Scheduler, prs: PullRequests,
               password: str | None, choices: Callable[[], list[str]], live: Live | None = None,
               cancel: Cancellation | None = None,
               settings: Callable[[], Settings] = Settings.from_env, lifespan=None) -> FastAPI:
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.router.route_class = _HeadAllowed
    basic = HTTPBasic(auto_error=False)
    live = live or Live()
    cancel = cancel or Cancellation()

    def authenticated(credentials: HTTPBasicCredentials | None = Depends(basic)) -> None:
        if not (password and credentials
                and hmac.compare_digest(credentials.password.encode(), password.encode())):
            raise HTTPException(401, headers={"WWW-Authenticate": 'Basic realm="upgrader"'})

    def status() -> dict:
        current = settings()
        due = None
        if not current.schedule_problems():
            due = next_run(now(), current.schedule_time, current.schedule_timezone)
        return {"dry_run": current.dry_run, "next_run": due, "timezone": current.schedule_timezone}

    def progress_context() -> dict:
        with Session() as session:
            run = session.scalars(
                select(Run).where(Run.finished_at.is_(None)).order_by(Run.id.desc()).limit(1)
            ).first()
            return {"run": run, "active": scheduler.active()}

    def index_page(request: Request, message: str | None = None, status_code: int = 200):
        with Session() as session:
            runs = session.scalars(select(Run).order_by(Run.id.desc()).limit(200)).all()
        return templates.TemplateResponse(request, "index.html", {
            "runs": runs, "choices": choices(), "message": message, "status": status(),
            **progress_context()}, status_code=status_code)

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz():
        return "ok"

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(authenticated)])
    def index(request: Request, message: str | None = None):
        return index_page(request, message)

    @app.get("/progress", response_class=HTMLResponse, dependencies=[Depends(authenticated)])
    def progress(request: Request):
        return templates.TemplateResponse(request, "_progress.html", progress_context())

    @app.get("/logbook", response_class=HTMLResponse, dependencies=[Depends(authenticated)])
    def logbook(request: Request):
        with Session() as session:
            runs = session.scalars(select(Run).order_by(Run.id.desc()).limit(200)).all()
        return templates.TemplateResponse(request, "_logbook.html", {"runs": runs})

    @app.get("/terminals", response_class=HTMLResponse, dependencies=[Depends(authenticated)])
    def terminals(request: Request):
        return templates.TemplateResponse(request, "_terminals.html", progress_context())

    @app.get("/live/{result_id}", response_class=HTMLResponse, dependencies=[Depends(authenticated)])
    def live_steps(request: Request, result_id: int, offset: int | None = Query(None, ge=0)):
        live_session = live.current(result_id)
        # A product is polled from the moment it starts, which is before its session is registered.
        steps, next_offset = read_live(live_session, offset) if live_session else ([], offset)
        with Session() as session:
            row = session.get(ProductResult, result_id)
            ended = row is None or row.finished_at is not None
        return templates.TemplateResponse(request, "_live_steps.html", {
            "result_id": result_id, "steps": steps, "offset": next_offset, "ended": ended})

    @app.post("/runs", dependencies=[Depends(authenticated)])
    def start(request: Request, product: str = Form("")):
        scope = product or None
        if scope and scope not in choices():
            raise HTTPException(400, f"{scope} is not an eligible product on master")
        if not scheduler.request(scope):
            return index_page(request, "A run is already in progress, so this request was not started.",
                              status_code=409)
        what = f"a run of {scope}" if scope else "a run of the whole catalog"
        return RedirectResponse(f"/?message=Started {what}.", status_code=303)

    @app.post("/runs/{run_id}/cancel", dependencies=[Depends(authenticated)])
    def cancel_run(request: Request, run_id: int):
        with Session() as session:
            run = session.get(Run, run_id)
        if not run:
            raise HTTPException(404)
        # The run may have finished between the page being rendered and the button being pressed.
        if run.finished_at or not cancel.request(run_id):
            return index_page(request, f"Run {run_id} is no longer active, so nothing was canceled.",
                              status_code=409)
        return RedirectResponse(f"/?message=Canceling run {run_id}.", status_code=303)

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
                "pr_state": prs.state(p.pr_url) if p.pr_url else None,
            })
        return templates.TemplateResponse(request, "run.html", {
            "run": run, "products": products, "status": status()})

    return app


def build() -> FastAPI:
    """The service as uvicorn runs it: `uvicorn --factory upgrader.web:build` (D1)."""
    from . import runner
    from .catalog import Choices, fetch
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

    choices = Choices(lambda: fetch(settings.repo_url, git=deps.git, workdir=deps.workdir))
    return create_app(Session, store, scheduler, PullRequests(app_client), settings.dashboard_password,
                      choices, live=deps.live, cancel=deps.cancel, lifespan=lifespan)
