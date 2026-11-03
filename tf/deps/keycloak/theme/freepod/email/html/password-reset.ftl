<#import "template.ftl" as layout>
<@layout.emailLayout>
  <h1 style="margin:0 0 16px 0; font-family:Georgia,'Times New Roman',serif;
             font-size:23px; font-weight:normal; color:#0B1020;">Reset your password</h1>

  <#if freepodApp??>
  <p style="margin:0 0 4px 0;">Someone — hopefully you — asked to reset the password
  you use to sign in to ${freepodApp.label}. ${freepodApp.label} is hosted on Freepod, so this
  is your Freepod account's password. Click the button below to choose a new one.</p>
  <#else>
  <p style="margin:0 0 4px 0;">Someone — hopefully you — asked to reset the password
  for your Freepod account. Click the button below to choose a new one.</p>
  </#if>

  <@layout.button href=link label="Reset my password" />

  <p style="margin:0 0 16px 0; font-size:14px; color:#6B7488;">
  This link expires in ${linkExpirationFormatter(linkExpiration)}. If you didn't request
  a password reset, you can safely ignore this email — nothing will change.</p>

  <p style="margin:0; font-size:13px; color:#8A93A8;">
  If the button doesn't work, copy and paste this link into your browser:<br/>
  <a href="${link}" style="color:#2563EB; word-break:break-all;">${link}</a></p>
</@layout.emailLayout>
