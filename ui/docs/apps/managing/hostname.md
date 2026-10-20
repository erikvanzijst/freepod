---
sidebar_position: 2
title: Hostname
---

# Hostname

An app's hostname is its address. Each app has one.

A Freepod hostname is the app's name followed by your handle: `photos-alice.freepod.app`. The app's name is 1 to 34 letters, digits and hyphens, does not start or end with a hyphen, and does not contain two hyphens in a row. Names that start with `preview-` are reserved. Each hostname can be used by one app at a time.

To use a domain you own instead, see [Custom domain](custom-domain.mdx).

## Changing the hostname

1. Select the app on the dashboard to expand its row, and select **Settings**.
2. Change **Hostname** and select **Update**.

The app is available at the new hostname once the update completes. The old hostname stops working immediately; links and bookmarks to it do not redirect.

:::warning

Changing the hostname can break an app. Many apps store their own address in links, shared items, mobile app connections and other users' bookmarks. Federated apps such as Matrix and Lemmy are identified on the network by their hostname: other servers do not recognize the app at a new hostname, and existing accounts, rooms and communities do not move with it. The [product guides](/apps/products) describe the effect for each app.

:::
