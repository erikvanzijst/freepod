<#--
  Freepod branded email shell.

  Email-safe by construction: table layout, inline styles, web-safe fonts
  (Georgia for the editorial wordmark/headings, Helvetica/Arial for body),
  light background. No <style> blocks or web fonts — clients strip/ignore them.

  - emailLayout: the outer chrome (dark Freepod header band, white card, footer).
    Per-flow templates nest their body inside it.
  - button: a bulletproof-ish CTA. Solid brand blue as the base (what Outlook
    renders) with a gradient layered on top for clients that support it.
-->

<#macro emailLayout>
<!DOCTYPE html>
<html lang="${locale.language}" dir="${(ltr)?then('ltr','rtl')}" xmlns="http://www.w3.org/1999/xhtml">
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

        <!-- Card -->
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
               style="width:600px; max-width:600px; background-color:#FFFFFF;
                      border:1px solid #E2E6EE; border-radius:16px; overflow:hidden;">

          <!-- Dark brand header band -->
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

          <!-- Gradient accent rule (solid fallback for Outlook) -->
          <tr>
            <td style="height:4px; line-height:4px; font-size:0;
                       background-color:#2563EB;
                       background-image:linear-gradient(90deg,#2563EB,#7C5BFF 55%,#EC4899);">&nbsp;</td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:34px 36px 12px 36px; font-family:Helvetica,Arial,sans-serif;
                       font-size:16px; line-height:1.6; color:#2A3142;">
              <#nested>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:24px 36px 30px 36px; border-top:1px solid #ECEFF5;
                       font-family:Helvetica,Arial,sans-serif; font-size:12px;
                       line-height:1.6; color:#8A93A8;">
              <strong style="color:#6B7488;">Freepod</strong> — private, EU-hosted apps,
              free of ads, tracking and lock-in.<br/>
              You received this email because it was requested for your account. If it
              wasn't you, you can safely ignore it.
            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>
</body>
</html>
</#macro>

<#--
  Branded CTA button. Usage: <@layout.button href=link label="Reset my password"/>
-->
<#macro button href label>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:26px 0 28px 0;">
  <tr>
    <td align="center" style="border-radius:999px; background-color:#2563EB;
        background-image:linear-gradient(120deg,#2563EB,#7C5BFF 55%,#EC4899);">
      <a href="${href}" target="_blank"
         style="display:inline-block; padding:14px 30px; font-family:Helvetica,Arial,sans-serif;
                font-size:16px; font-weight:bold; color:#FFFFFF; text-decoration:none;
                border-radius:999px;">${label}</a>
    </td>
  </tr>
</table>
</#macro>
