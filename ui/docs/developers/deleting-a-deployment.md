---
sidebar_position: 13
title: Deleting a deployment
---

# Deleting a deployment

```bash
freepod delete
```

deletes the project's deployment after asking for confirmation, and waits until the deletion has finished. `--yes` skips the confirmation, and is required when there is no terminal. `--no-wait` returns once the deletion has started.

A deployment can also be deleted from the [dashboard](app:/).

Deleting a deployment:

- stops the application and frees its hostname once the deletion has finished;
- deletes its [PostgreSQL database](storage/postgresql.mdx) and [object storage bucket](storage/object-storage.mdx). Access ends immediately; the data is destroyed after one day and cannot be recovered;
- deletes its variables;
- ends usage metering for it.

**Back up any data you need before deleting.** Freepod does not restore deleted deployments.

`.freepod.json` keeps its settings. The next `freepod deploy` in the project creates a new, empty deployment with the same hostname.
