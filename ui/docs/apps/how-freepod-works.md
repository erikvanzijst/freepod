---
sidebar_position: 2
title: How Freepod works
---

# How Freepod works

## Account

A Freepod account belongs to one person and is identified by an email address. Each account has one [subdomain](get-started.md#2-choose-your-subdomain), such as `alice.freepod.eu`.

## Apps

An app is one running copy of a product from the catalog, such as Immich or Nextcloud, launched from your account. Each app:

- has its own hostname, under your subdomain or on a [custom domain](managing/custom-domain.mdx);
- stores its own data, separate from your other apps and from other accounts;
- has a [plan](plans-and-billing.md) that sets its price and storage.

You can run several apps, including several copies of the same product.

## Who does what

| Freepod | You |
| --- | --- |
| Installs and runs the app | Choose the app, its plan and hostname |
| Provides HTTPS certificates | Set up and use the app itself: accounts, content, its own settings |
| [Updates](managing/automatic-updates.md) the app automatically | Keep your own copies of data you cannot lose; see [Your data](your-data.md) |

Using an app — its features, its accounts, its configuration screens — is covered by the app's own documentation, linked from each [product guide](/apps/products).

## Developer deployments

Freepod also runs applications you build yourself, deployed with the `freepod` command-line client. They appear on the dashboard alongside catalog apps. See the [developer documentation](/developers).
