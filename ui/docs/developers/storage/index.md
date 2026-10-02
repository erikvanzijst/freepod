# Storage

A deployment's filesystem is not persistent. Persistent state goes in the two stores every deployment gets:

| | [PostgreSQL](postgresql.mdx) | [Object storage](object-storage.mdx) |
| --- | --- | --- |
| Use for | Structured data, sessions, queues | Files, uploads, exports, backups |
| Access | `DATABASE_URL`, `PG*` variables | S3 API, `AWS_*` and `S3_BUCKET` variables |
| Allowance | 100 MiB | 1 GiB |

Both are created with the deployment and need no setup; their credentials are in the container's environment.

- Each store belongs to exactly one deployment. It cannot be shared with or reached from another deployment.
- There is no other storage: no persistent disk, no Redis, no MySQL.
- Deleting a deployment deletes both stores. Access ends immediately and the data is destroyed after one day. See [Deleting a deployment](../deleting-a-deployment.md).

## Backups

Freepod has processes in place to protect the platform's data and its users' data. It does not restore individual databases or buckets on request. Deployments whose data matters should keep their own backups.

To back up:

- PostgreSQL: `freepod shell pg_dump > backup.sql`. See [PostgreSQL: Backups](postgresql.mdx#backups).
- Object storage: copy objects out with any S3 client, using the credentials from `freepod shell env`.
