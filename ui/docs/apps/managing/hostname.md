---
sidebar_position: 2
title: Hostname
---

# Hostname

An app's hostname is its address. Each app has one.

A hostname under your subdomain has one name in front of it: `photos.alice.freepod.eu`. The name is 1 to 63 letters, digits and hyphens, and does not start or end with a hyphen. Each hostname can be used by one app at a time.

To use a domain you own instead, see [Custom domain](custom-domain.mdx).

## Changing the hostname

1. Select **Edit** on the app's card.
2. Change **Hostname** and select **Update**.

The app is available at the new hostname once the update completes. The old hostname stops working immediately; links and bookmarks to it do not redirect.

:::warning

Changing the hostname can break an app. Many apps store their own address in links, shared items, mobile app connections and other users' bookmarks. Federated apps such as Matrix and Lemmy are identified on the network by their hostname: other servers do not recognize the app at a new hostname, and existing accounts, rooms and communities do not move with it. The [product guides](/apps/products) describe the effect for each app.

:::
