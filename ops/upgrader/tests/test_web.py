import threading
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from upgrader import db
from upgrader.github import PullRequests
from upgrader.scheduler import Scheduler
from upgrader.store import S3Store
from upgrader.web import create_app

from .fakes import FakeGitHub, MemoryStore

AUTH = ("owner", "correct horse")


@pytest.fixture
def github():
    return FakeGitHub()


@pytest.fixture
def release():
    return threading.Event()


@pytest.fixture
def calls():
    return []


@pytest.fixture
def scheduler(calls, release):
    def execute(trigger, scope):
        calls.append((trigger, scope))
        release.wait(5)

    s = Scheduler(execute)
    yield s
    release.set()


def client(Session, scheduler, github, password="correct horse", store=None):
    app = create_app(Session, store or MemoryStore(), scheduler,
                     PullRequests(None, http=github.client()), password)
    return TestClient(app)


def add_run(Session, *products, scope=None, finished=True, **fields):
    with Session.begin() as s:
        run = db.Run(trigger="scheduled", scope=scope, dry_run=True, **fields)
        run.products = list(products)
        if finished:
            run.state, run.finished_at = "completed", db.now()
        s.add(run)
    return run


def product(slug, outcome="up_to_date", finished=True, **fields):
    fields.setdefault("needs_human", [])
    p = db.ProductResult(slug=slug, outcome=outcome, current_version="1.0.0", **fields)
    if finished:
        p.finished_at = p.started_at = db.now()
    return p


def test_healthz_needs_no_credentials(Session, scheduler, github):
    assert client(Session, scheduler, github).get("/healthz").status_code == 200


@pytest.mark.parametrize("auth", [None, ("owner", "wrong"), ("", "")])
def test_pages_need_the_password(Session, scheduler, github, auth):
    c = client(Session, scheduler, github)
    for path in ("/", "/progress", "/runs/1"):
        response = c.get(path, auth=auth)
        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Basic")
    assert c.post("/runs", auth=auth).status_code == 401


@pytest.mark.parametrize("password", [None, ""])
def test_an_unset_password_refuses_everything(Session, scheduler, github, password):
    c = client(Session, scheduler, github, password=password)
    assert c.get("/", auth=AUTH).status_code == 401
    assert c.get("/", auth=("owner", "")).status_code == 401
    assert c.get("/healthz").status_code == 200


def test_the_username_is_not_checked(Session, scheduler, github):
    assert client(Session, scheduler, github).get("/", auth=("anyone", "correct horse")).status_code == 200


def test_history_is_newest_first_and_marks_the_mode(Session, scheduler, github):
    old = add_run(Session, product("immich"))
    new = add_run(Session, product("immich", "would_open", branch="upgrade/immich-v3.2.1"))
    page = client(Session, scheduler, github).get("/", auth=AUTH).text
    assert page.index(f'href="/runs/{new.id}"') < page.index(f'href="/runs/{old.id}"')
    assert "dry run" in page and "1 would open" in page


def test_a_would_open_product_shows_its_description_and_patch(Session, scheduler, github):
    store = MemoryStore()
    run = add_run(Session, product(
        "immich", "would_open", target_version="v3.2.1", branch="upgrade/immich-v3.2.1", draft=True,
        needs_human=["Confirm x86-64-v2"],
        files=["session.jsonl", "session.html", "stdout.txt", "result.json", "body.md", "change.patch"]))
    page = client(Session, scheduler, github, store=store).get(f"/runs/{run.id}", auth=AUTH).text
    prefix = f"https://blob.test/bucket/runs/{run.id}/immich/"
    assert f'<iframe src="{prefix}body.md?' in page
    assert f'<iframe src="{prefix}change.patch?' in page
    assert f'href="{prefix}session.html?' in page
    assert "Would open a draft from <code>upgrade/immich-v3.2.1</code>" in page
    assert "Confirm x86-64-v2" in page


def test_signed_links_expire_within_an_hour():
    import boto3

    s3 = boto3.client("s3", endpoint_url="https://blob.freepod.eu", region_name="garage",
                      aws_access_key_id="GK", aws_secret_access_key="secret")
    url = S3Store(bucket="b", client=s3).url("runs/1/immich/session.html")
    query = parse_qs(urlparse(url).query)
    assert urlparse(url).path == "/b/runs/1/immich/session.html"
    assert int(query["X-Amz-Expires"][0]) <= 3600


def test_pr_state_from_github(Session, scheduler, github):
    github.pulls[12] = {"state": "closed", "draft": False, "merged": True}
    run = add_run(Session, product("vaultwarden", "opened", draft=False,
                                   pr_url="https://github.com/erikvanzijst/freepod/pull/12"))
    page = client(Session, scheduler, github).get(f"/runs/{run.id}", auth=AUTH).text
    assert "(merged)" in page


def test_unreachable_github_still_renders(Session, scheduler, github):
    github.down = True
    run = add_run(Session, product("vaultwarden", "opened", draft=False,
                                   pr_url="https://github.com/erikvanzijst/freepod/pull/13"))
    response = client(Session, scheduler, github).get(f"/runs/{run.id}", auth=AUTH)
    assert response.status_code == 200 and "(unknown)" in response.text


def test_product_choices_come_from_the_latest_catalog_run(Session, scheduler, github):
    add_run(Session, product("immich"), product("nextcloud"))
    add_run(Session, product("immich"), product("nextcloud"), product("vaultwarden"))
    add_run(Session, product("immich"), scope="immich")
    page = client(Session, scheduler, github).get("/", auth=AUTH).text
    assert [s for s in ("immich", "nextcloud", "vaultwarden") if f'<option value="{s}">' in page] == [
        "immich", "nextcloud", "vaultwarden"]


def test_run_now_and_run_one_product(Session, scheduler, github, calls, release):
    add_run(Session, product("immich"), product("nextcloud"))
    c = client(Session, scheduler, github)
    response = c.post("/runs", data={"product": "nextcloud"}, auth=AUTH, follow_redirects=False)
    assert response.status_code == 303
    assert "Started a run of nextcloud" in c.get(response.headers["location"], auth=AUTH).text
    for request in ({}, {"product": "immich"}):
        refused = c.post("/runs", data=request, auth=AUTH)
        assert refused.status_code == 409 and "already in progress" in refused.text
    assert "disabled" in c.get("/", auth=AUTH).text
    release.set()
    deadline = time.monotonic() + 5
    while scheduler.active() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert c.post("/runs", data={}, auth=AUTH, follow_redirects=False).status_code == 303
    assert calls[:2] == [("manual", "nextcloud"), ("manual", None)]


def test_a_product_outside_the_choices_is_refused(Session, scheduler, github, calls):
    add_run(Session, product("immich"))
    response = client(Session, scheduler, github).post("/runs", data={"product": "custom"}, auth=AUTH)
    assert response.status_code == 400 and calls == []


def test_progress_names_the_running_product_and_finished_outcomes(Session, scheduler, github):
    running = product("nextcloud", "running", finished=False)
    running.started_at = db.now() - timedelta(minutes=12, seconds=5)
    add_run(Session, product("immich", "would_open", branch="upgrade/x"), running, finished=False)
    fragment = client(Session, scheduler, github).get("/progress", auth=AUTH).text
    assert 'hx-trigger="every 5s"' in fragment
    assert "nextcloud: running for 12m0" in fragment
    assert "immich:" in fragment and "would open" in fragment


def test_pages_answer_while_a_run_is_in_progress(Session, scheduler, github, calls):
    c = client(Session, scheduler, github)
    assert scheduler.request(None)
    deadline = time.monotonic() + 5
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    started = time.monotonic()
    assert c.get("/", auth=AUTH).status_code == 200
    assert c.get("/healthz").status_code == 200
    assert time.monotonic() - started < 2
    assert scheduler.active()
