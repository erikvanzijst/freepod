locals {
  # PostgreSQL 18.6, supported to 2030-11-14 (design D14). Pinned to the patch
  # release rather than `18-alpine`: which version the tenant cluster runs is a
  # decision, not whatever a moving tag resolved to the day a pod restarted.
  tenant_db_image = "postgres:18.6-alpine"

  tenant_db_exporter_image = "quay.io/prometheuscommunity/postgres-exporter:v0.20.1"

  # PgBouncer >= 1.21 is a hard floor, not a preference: protocol-level prepared
  # statement support (`max_prepared_statements`) arrived there, and asyncpg,
  # SQLAlchemy, Prisma and node-postgres all use prepared statements by default.
  tenant_pooler_image = "edoburu/pgbouncer:v1.25.2-p0"

  # One name for the pooler's pod label. The tenant NetworkPolicy selects
  # egress on it (CAELUS_TENANT_DB_POOLER_POD_LABEL), so a drift between the
  # two would leave every tenant unable to reach its database.
  tenant_pooler_app_label = "caelus-tenant-pooler"
}
