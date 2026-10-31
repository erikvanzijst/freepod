"""Freepod's branded email layout, for the mail the platform sends itself.

The look is Keycloak's email theme (tf/deps/keycloak/theme/freepod/email/
html/template.ftl), so account mail and platform mail arrive alike: table
layout, inline styles and web-safe fonts, since mail clients strip <style>
blocks and ignore web fonts. Change the two together.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape


@dataclass(frozen=True)
class Button:
    label: str
    href: str


def compose(
    *,
    heading: str,
    paragraphs: Sequence[str],
    reason: str,
    button: Button | None = None,
    note: str | None = None,
) -> tuple[str, str]:
    """One message as (plain text, HTML). Every argument is text, not markup.

    `note` is a smaller line under the button, like the theme's expiry line;
    `reason` closes the footer, saying why the recipient got the mail.
    """
    text = list(paragraphs)
    if button is not None:
        text.append(button.href)
    if note:
        text.append(note)
    return "\n\n".join(text) + "\n", _html(heading, paragraphs, reason, button, note)


def _html(
    heading: str, paragraphs: Sequence[str], reason: str, button: Button | None, note: str | None
) -> str:
    body = [
        (
            '<h1 style="margin:0 0 16px 0; font-family:Georgia,\'Times New Roman\',serif;'
            f' font-size:23px; font-weight:normal; color:#0B1020;">{escape(heading)}</h1>'
        )
    ]
    body += [f'<p style="margin:0 0 16px 0;">{escape(p)}</p>' for p in paragraphs]
    if button is not None:
        body.append(_button(button))
    if note:
        body.append(
            f'<p style="margin:0 0 16px 0; font-size:14px; color:#6B7488;">{escape(note)}</p>'
        )
    if button is not None:
        href = escape(button.href)
        body.append(
            '<p style="margin:0 0 16px 0; font-size:13px; color:#8A93A8;">'
            "If the button doesn't work, copy and paste this link into your browser:<br/>"
            f'<a href="{href}" style="color:#2563EB; word-break:break-all;">{href}</a></p>'
        )
    return _SHELL.format(body="\n".join(body), reason=escape(reason))


def _button(button: Button) -> str:
    return f"""<table role="presentation" cellpadding="0" cellspacing="0" border="0"
       style="margin:26px 0 28px 0;">
  <tr>
    <td align="center" style="border-radius:999px; background-color:#2563EB;
        background-image:linear-gradient(120deg,#2563EB,#7C5BFF 55%,#EC4899);">
      <a href="{escape(button.href)}" target="_blank"
         style="display:inline-block; padding:14px 30px; font-family:Helvetica,Arial,sans-serif;
                font-size:16px; font-weight:bold; color:#FFFFFF; text-decoration:none;
                border-radius:999px;">{escape(button.label)}</a>
    </td>
  </tr>
</table>"""


_SHELL = """<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta http-equiv="X-UA-Compatible" content="IE=edge"/>
  <title>Freepod</title>
</head>
<body style="margin:0; padding:0; background-color:#EAEDF3;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background-color:#EAEDF3;">
    <tr>
      <td align="center" style="padding:32px 16px;">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
               style="width:600px; max-width:600px; background-color:#FFFFFF;
                      border:1px solid #E2E6EE; border-radius:16px; overflow:hidden;">
          <tr>
            <td style="background-color:#0B1020; padding:30px 36px 26px 36px;">
              <div style="font-family:Georgia,'Times New Roman',serif; font-size:27px;
                          font-weight:bold; color:#F4F6FB; letter-spacing:-0.5px;
                          line-height:1;">Freepod</div>
              <div style="font-family:Helvetica,Arial,sans-serif; font-size:11px;
                          letter-spacing:3px; text-transform:uppercase; color:#38BDF8;
                          margin-top:10px;">The European cloud</div>
            </td>
          </tr>
          <tr>
            <td style="height:4px; line-height:4px; font-size:0;
                       background-color:#2563EB;
                       background-image:linear-gradient(90deg,#2563EB,#7C5BFF 55%,#EC4899);"
            >&nbsp;</td>
          </tr>
          <tr>
            <td style="padding:34px 36px 12px 36px; font-family:Helvetica,Arial,sans-serif;
                       font-size:16px; line-height:1.6; color:#2A3142;">
{body}
            </td>
          </tr>
          <tr>
            <td style="padding:24px 36px 30px 36px; border-top:1px solid #ECEFF5;
                       font-family:Helvetica,Arial,sans-serif; font-size:12px;
                       line-height:1.6; color:#8A93A8;">
              <strong style="color:#6B7488;">Freepod</strong> — private, EU-hosted apps,
              free of ads, tracking and lock-in.<br/>
              {reason}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
