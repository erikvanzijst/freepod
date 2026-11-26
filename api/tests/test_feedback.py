"""feedback-api and feedback-notification."""

from __future__ import annotations

import io
import json
from datetime import timedelta

import pytest
from PIL import Image
from sqlmodel import select

from app.config import get_settings
from app.models import FeedbackORM, FeedbackScreenshotORM, NotificationORM, UserORM
from app.models.core import _utcnow
from app.services import feedback as feedback_service
from app.services.errors import InvalidInputException
from app.services.notifications import md
from tests.conftest import ADMIN_EMAIL, USER_AUTH_HEADER, USER_EMAIL, auth_header


def _jpeg(size=(320, 200), exif: bool = False) -> bytes:
    img = Image.new("RGB", size, (200, 30, 30))
    out = io.BytesIO()
    if exif:
        data = Image.Exif()
        data[0x010F] = "SecretCam"
        data[0x0132] = "2026:11:26 10:00:00"
        img.save(out, format="JPEG", exif=data.tobytes())
    else:
        img.save(out, format="JPEG")
    return out.getvalue()


def _post(client, headers=USER_AUTH_HEADER, files=None, **fields):
    data = {"topic": "bug", "message": "The deploy button does nothing", "page": "/settings/handle"}
    data.update(fields)
    return client.post("/api/feedback", data=data, files=files, headers=headers)


def _rows(db_session) -> list[FeedbackORM]:
    return db_session.exec(select(FeedbackORM).order_by(FeedbackORM.id)).all()


def _notices(db_session) -> list[NotificationORM]:
    return db_session.exec(select(NotificationORM).where(NotificationORM.kind == "feedback.submitted")).all()


@pytest.fixture
def user(user_client):
    return user_client[0]


@pytest.fixture
def settings_env(monkeypatch):
    def apply(**env):
        for key, value in env.items():
            monkeypatch.setenv(f"CAELUS_{key.upper()}", value)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


@pytest.fixture
def mailed(settings_env):
    settings_env(feedback_email="feedback@freepod.example", base_url="https://freepod.example")


# ── page normalization ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "page, stored",
    [
        ("/apps/immich?tab=plans#pricing", "/apps/immich?tab=plans"),
        ("/settings/git?code=abc&state=xyz&installation_id=7", "/settings/git?installation_id=7"),
        ("/x?token=1&access_token=2&client_secret=3&ID_TOKEN=4&keep=5", "/x?keep=5"),
        ("/x?code=1", "/x"),
        ("/x?a=1&b=&a=2", "/x?a=1&b=&a=2"),
        ("/", "/"),
    ],
)
def test_normalize_page(page, stored):
    assert feedback_service.normalize_page(page) == stored


@pytest.mark.parametrize(
    "page",
    ["https://example.com/x", "//example.com/x", "/\\example.com", "apps", "", "javascript:alert(1)", "/a\nb"],
)
def test_normalize_page_refuses_other_sites(page):
    with pytest.raises(InvalidInputException) as e:
        feedback_service.normalize_page(page)
    assert e.value.code == "invalid_page"


# ── screenshots ───────────────────────────────────────────────────────────


def test_a_screenshot_is_reencoded_without_exif():
    data, width, height = feedback_service.process_feedback_screenshot(_jpeg(exif=True))
    img = Image.open(io.BytesIO(data))
    assert img.format == "WEBP" and (width, height) == (320, 200)
    assert not img.getexif()
    assert b"SecretCam" not in data


def test_a_pdf_is_not_a_screenshot():
    with pytest.raises(ValueError):
        feedback_service.process_feedback_screenshot(b"%PDF-1.7\n1 0 obj << >> endobj\n")


def test_an_oversize_file_is_refused():
    with pytest.raises(ValueError, match="2 MB"):
        feedback_service.process_feedback_screenshot(b"\xff" * (2 * 1024 * 1024 + 1))


def test_oversized_dimensions_are_refused():
    img = Image.new("1", (4097, 10))
    out = io.BytesIO()
    img.save(out, format="PNG")
    with pytest.raises(ValueError, match="4096"):
        feedback_service.process_feedback_screenshot(out.getvalue())


# ── diagnostics ───────────────────────────────────────────────────────────


def test_diagnostics_keep_the_newest_twenty_flat_entries():
    raw = json.dumps(
        [{"kind": "error", "message": f"e{i}", "at": i} for i in range(30)]
        + [{"kind": "console", "message": "x" * 600, "nested": {"a": 1}, "list": [1]}]
    )
    entries = feedback_service.sanitize_diagnostics(raw)
    assert len(entries) == 20
    assert entries[0]["message"] == "e11"
    assert entries[-1] == {"kind": "console", "message": "x" * 500}


def test_diagnostics_stay_under_32_kb():
    raw = json.dumps([{f"k{j}": "y" * 500 for j in range(12)} for _ in range(20)])
    entries = feedback_service.sanitize_diagnostics(raw)
    assert len(json.dumps(entries)) <= 32 * 1024
    assert entries


@pytest.mark.parametrize("raw", [None, "", "not json", '{"a": 1}', "[1, \"x\"]"])
def test_malformed_diagnostics_become_an_empty_list(raw):
    assert feedback_service.sanitize_diagnostics(raw) == []


# ── submitting ────────────────────────────────────────────────────────────


def test_submitted_with_a_screenshot(user, db_session):
    resp = _post(user, files={"screenshot": ("shot.jpg", _jpeg(), "image/jpeg")})
    assert resp.status_code == 201, resp.text
    [row] = _rows(db_session)
    assert resp.json() == {"id": row.id}
    sender = db_session.exec(select(UserORM).where(UserORM.email == USER_EMAIL)).one()
    assert (row.user_id, row.email, row.page) == (sender.id, USER_EMAIL, "/settings/handle")
    shot = db_session.get(FeedbackScreenshotORM, row.id)
    assert shot.media_type == "image/webp" and (shot.width, shot.height) == (320, 200)


def test_context_fields_are_stored(user, db_session):
    resp = _post(
        user,
        user_agent="Mozilla/5.0 Test",
        viewport="1440x900",
        ui_build="4eaa51e",
        diagnostics=json.dumps([{"kind": "api", "method": "GET", "path": "/api/me", "status": 500}]),
    )
    assert resp.status_code == 201
    [row] = _rows(db_session)
    assert (row.user_agent, row.viewport, row.ui_build) == ("Mozilla/5.0 Test", "1440x900", "4eaa51e")
    assert row.diagnostics == [{"kind": "api", "method": "GET", "path": "/api/me", "status": 500}]


def test_anonymous_feedback_is_refused(user, db_session):
    resp = user.post(
        "/api/feedback",
        data={"topic": "bug", "message": "hi", "page": "/"},
        headers={"X-Auth-Request-Email": "", "X-Auth-Request-User": ""},
    )
    assert resp.status_code == 404
    assert _rows(db_session) == []


def test_the_sender_is_the_caller(user, db_session):
    resp = _post(user, email=ADMIN_EMAIL, user_id="1", resolved="true", sender=ADMIN_EMAIL)
    assert resp.status_code == 201
    [row] = _rows(db_session)
    assert row.email == USER_EMAIL and row.resolved_at is None


@pytest.mark.parametrize(
    "env, expected", [({"GIT_COMMIT": "4eaa51e"}, "4eaa51e"), ({"GIT_COMMIT": "unknown"}, None), ({}, None)]
)
def test_the_api_records_its_own_build(user, db_session, monkeypatch, env, expected):
    monkeypatch.delenv("GIT_COMMIT", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert _post(user, api_build="deadbee", ui_build="1234567").status_code == 201
    [row] = _rows(db_session)
    assert row.api_build == expected
    assert row.ui_build == "1234567"


@pytest.mark.parametrize(
    "fields, code",
    [
        ({"topic": "praise"}, "invalid_topic"),
        ({"message": "   "}, "message_required"),
        ({"message": "x" * 5001}, "message_too_long"),
        ({"page": "https://example.com/x"}, "invalid_page"),
        ({"page": "//example.com/x"}, "invalid_page"),
    ],
)
def test_invalid_submissions_are_refused(user, db_session, mailed, fields, code):
    resp = _post(user, **fields)
    assert resp.status_code == 422
    assert resp.json()["code"] == code
    assert _rows(db_session) == [] and _notices(db_session) == []


def test_a_pdf_screenshot_is_refused(user, db_session):
    resp = _post(user, files={"screenshot": ("x.pdf", b"%PDF-1.7\n", "application/pdf")})
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_screenshot"
    assert _rows(db_session) == []


def test_a_secret_query_is_stripped_before_storing(user, db_session):
    assert _post(user, page="/settings/git?code=abc&state=xyz&installation_id=7").status_code == 201
    assert _rows(db_session)[0].page == "/settings/git?installation_id=7"


def test_the_twenty_first_submission_in_a_day_is_refused(user, db_session, mailed):
    for _ in range(20):
        assert _post(user).status_code == 201
    resp = _post(user)
    assert resp.status_code == 429
    assert resp.json()["code"] == "feedback_limit"
    assert "UTC" in resp.json()["detail"]
    assert len(_rows(db_session)) == 20 and len(_notices(db_session)) == 20


def test_the_limit_counts_only_the_past_24_hours(user, db_session):
    for _ in range(20):
        assert _post(user).status_code == 201
    for row in _rows(db_session):
        row.created_at = _utcnow() - timedelta(hours=25)
        db_session.add(row)
    db_session.commit()
    assert _post(user).status_code == 201


def test_the_browsers_own_headers_pass_the_gates(user, db_session):
    resp = _post(
        user,
        headers={
            **USER_AUTH_HEADER,
            "Origin": "https://testserver",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/145.0",
        },
        files={"screenshot": ("shot.jpg", _jpeg(), "image/jpeg")},
    )
    assert resp.status_code == 201, resp.text


def test_a_cross_site_submission_is_refused(user, db_session):
    resp = _post(user, headers={**USER_AUTH_HEADER, "Sec-Fetch-Site": "cross-site"})
    assert resp.status_code == 403
    assert _rows(db_session) == []


# ── the email ─────────────────────────────────────────────────────────────


def test_production_emails_the_feedback_address(user, db_session, settings_env):
    settings_env(feedback_email="feedback@freepod.eu", base_url="https://freepod.eu", environment="prod")
    assert _post(user, topic="idea", message="Let me pick the region for my app").status_code == 201
    [row] = _rows(db_session)
    [notice] = _notices(db_session)
    assert notice.recipient_email == "feedback@freepod.eu" and notice.recipient_user_id is None
    assert notice.subject == "Feedback · An idea: Let me pick the region for my app"
    assert (notice.action_label, notice.action_url) == (
        "View in Admin",
        f"https://freepod.eu/admin/feedback/{row.id}",
    )
    assert md(USER_EMAIL) in notice.body
    assert "[" + md("/settings/handle") + "](https://freepod.eu/settings/handle)" in notice.body
    assert "**Screenshot:** none" in notice.body


def test_no_address_queues_nothing(user, db_session, settings_env):
    settings_env(feedback_email="")
    assert _post(user).status_code == 201
    assert len(_rows(db_session)) == 1 and _notices(db_session) == []


def test_development_marks_the_subject(user, db_session, settings_env):
    settings_env(feedback_email="feedback@freepod.eu", environment="dev")
    assert _post(user, message="x" * 80 + "\nsecond line").status_code == 201
    [notice] = _notices(db_session)
    assert notice.subject == "[dev] Feedback · Something is wrong: " + "x" * 59 + "…"


def test_plain_http_has_no_action(user, db_session, settings_env):
    settings_env(feedback_email="feedback@freepod.eu", base_url="http://localhost:5173")
    assert _post(user).status_code == 201
    [notice] = _notices(db_session)
    assert notice.action_url is None and notice.action_label is None


def test_markup_in_the_message_is_text(user, db_session, mailed):
    message = "See [click](https://evil.example) and <b>bold</b>"
    assert _post(user, message=message, page="/x?q=<script>").status_code == 201
    [notice] = _notices(db_session)
    assert md(message) in notice.body
    assert "](https://evil.example)" not in notice.body
    assert "<b>" not in notice.body and "<script>" not in notice.body


def test_the_screenshot_is_mentioned_not_attached(user, db_session, mailed):
    assert _post(user, files={"screenshot": ("s.jpg", _jpeg(), "image/jpeg")}).status_code == 201
    [notice] = _notices(db_session)
    assert "**Screenshot:** attached in Admin" in notice.body


# ── administrators ────────────────────────────────────────────────────────


def _seed(client, n=1, **fields) -> list[int]:
    return [_post(client, **fields).json()["id"] for _ in range(n)]


def test_listing_is_for_administrators_only(user):
    assert user.get("/api/feedback", headers=USER_AUTH_HEADER).status_code == 403


def test_admins_list_open_items_newest_first(client, db_session):
    first, second, third = _seed(client, 3, headers=auth_header(ADMIN_EMAIL))
    client.patch(f"/api/feedback/{second}", json={"resolved": True})
    body = client.get("/api/feedback").json()
    assert [i["id"] for i in body["items"]] == [third, first]
    assert body["total"] == 2 and body["unread"] == 3
    assert body["items"][0]["read"] is False and body["items"][0]["has_screenshot"] is False
    assert "message" not in body["items"][0] and "data" not in body["items"][0]
    resolved = client.get("/api/feedback?state=resolved").json()
    assert [i["id"] for i in resolved["items"]] == [second]
    assert client.get("/api/feedback?state=all").json()["total"] == 3


def test_admins_filter_by_topic_and_page(client):
    _seed(client, 2, headers=auth_header(ADMIN_EMAIL), topic="idea")
    _seed(client, 1, headers=auth_header(ADMIN_EMAIL), topic="bug")
    assert client.get("/api/feedback?topic=idea").json()["total"] == 2
    page = client.get("/api/feedback?limit=1&offset=1").json()
    assert len(page["items"]) == 1 and page["total"] == 3
    counts = client.get("/api/feedback?limit=0").json()
    assert counts["items"] == [] and counts["unread"] == 3


def test_the_first_read_marks_it_read(client):
    [fid] = _seed(client, headers=auth_header(ADMIN_EMAIL))
    body = client.get(f"/api/feedback/{fid}").json()
    assert body["message"] == "The deploy button does nothing" and body["read_at"] is not None
    assert client.get(f"/api/feedback/{fid}").json()["read_at"] == body["read_at"]
    assert client.get("/api/feedback?limit=0").json()["unread"] == 0


def test_reading_one_is_for_administrators_only(user):
    fid = _post(user).json()["id"]
    assert user.get(f"/api/feedback/{fid}", headers=USER_AUTH_HEADER).status_code == 403
    assert user.patch(
        f"/api/feedback/{fid}", json={"resolved": True}, headers=USER_AUTH_HEADER
    ).status_code == 403


def test_the_screenshot_is_served_privately(client):
    fid = _post(
        client, headers=auth_header(ADMIN_EMAIL), files={"screenshot": ("s.jpg", _jpeg(), "image/jpeg")}
    ).json()["id"]
    resp = client.get(f"/api/feedback/{fid}/screenshot")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/webp"
    assert resp.headers["cache-control"] == "private, no-store"
    assert Image.open(io.BytesIO(resp.content)).size == (320, 200)
    detail = client.get(f"/api/feedback/{fid}").json()
    assert detail["has_screenshot"] is True and detail["screenshot_width"] == 320


def test_no_screenshot_is_404(client):
    [fid] = _seed(client, headers=auth_header(ADMIN_EMAIL))
    resp = client.get(f"/api/feedback/{fid}/screenshot")
    assert resp.status_code == 404 and resp.json()["code"] == "feedback_screenshot_not_found"
    assert client.get("/api/feedback/999999").status_code == 404


def test_a_sender_cannot_read_their_own_screenshot(user):
    fid = _post(user, files={"screenshot": ("s.jpg", _jpeg(), "image/jpeg")}).json()["id"]
    assert user.get(f"/api/feedback/{fid}/screenshot", headers=USER_AUTH_HEADER).status_code == 403


def test_resolve_twice_keeps_the_first_resolver(client, db_session):
    [fid] = _seed(client, headers=auth_header(ADMIN_EMAIL))
    first = client.patch(f"/api/feedback/{fid}", json={"resolved": True}).json()
    assert first["resolved_by_email"] == ADMIN_EMAIL and first["resolved_at"]
    db_session.add(UserORM(email="second-admin@example.com", is_admin=True))
    db_session.commit()
    again = client.patch(
        f"/api/feedback/{fid}", json={"resolved": True}, headers=auth_header("second-admin@example.com")
    ).json()
    assert (again["resolved_at"], again["resolved_by"]) == (first["resolved_at"], first["resolved_by"])


def test_reopen_clears_the_resolver_and_stays_read(client):
    [fid] = _seed(client, headers=auth_header(ADMIN_EMAIL))
    client.get(f"/api/feedback/{fid}")
    client.patch(f"/api/feedback/{fid}", json={"resolved": True})
    body = client.patch(f"/api/feedback/{fid}", json={"resolved": False}).json()
    assert body["resolved_at"] is None and body["resolved_by"] is None and body["resolved_by_email"] is None
    assert body["read_at"] is not None
