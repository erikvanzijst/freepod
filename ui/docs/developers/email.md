---
sidebar_position: 9.5
title: Email
---

# Email

Freepod does not provide email for developer deployments. There is no mail server or relay for deployments to send through, and deployments cannot receive email.

To send email, use an external email provider. Outbound connections are not restricted, so both work:

- a provider's API;
- SMTP submission to the provider, on port 587 or 465.

Store the provider's credentials as [secrets](variables-and-secrets.md#secrets).
