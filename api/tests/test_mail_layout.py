from email.message import EmailMessage

from app.config import CaelusSettings
from app.services import mail_layout, mailer


def _compose(**kw):
    args = {"heading": "Hello", "paragraphs": ["First.", "Second."], "reason": "Because."}
    return mail_layout.compose(**(args | kw))


def test_text_and_html_carry_the_same_content():
    text, html = _compose(button=mail_layout.Button("Open", "https://a.example/"), note="Soon.")
    assert text == "First.\n\nSecond.\n\nhttps://a.example/\n\nSoon.\n"
    for part in ("Hello", "First.", "Second.", 'href="https://a.example/"', ">Open</a>", "Soon.",
                 "Because."):
        assert part in html


def test_no_button_no_fallback_link():
    _, html = _compose()
    assert "<a " not in html and "copy and paste" not in html


def test_everything_is_escaped():
    _, html = _compose(
        heading="<h>",
        paragraphs=["<script>x</script>"],
        reason="a&b",
        button=mail_layout.Button("<b>", 'https://a.example/"onclick="x'),
    )
    for raw in ("<h>", "<script>", "a&b", "<b>", '"onclick="'):
        assert raw not in html
    assert "&lt;script&gt;" in html and "a&amp;b" in html and "&quot;onclick=&quot;" in html


def test_mailer_sends_text_with_an_html_alternative(monkeypatch):
    sent: list[EmailMessage] = []

    class SMTP:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr(mailer.smtplib, "SMTP", SMTP)
    settings = CaelusSettings(smtp_host="relay", smtp_from="Freepod <no-reply@example.com>")
    text, html = _compose()
    assert mailer.send_email(
        to="a@example.com", subject="S", body=text, html=html, settings=settings
    )
    [message] = sent
    assert message.get_content_type() == "multipart/alternative"
    assert message.get_body(("plain",)).get_content() == text
    assert message.get_body(("html",)).get_content() == html
