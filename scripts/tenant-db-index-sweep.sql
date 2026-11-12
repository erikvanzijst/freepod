-- Index and constraint sweep for one database on the tenant cluster, after the
-- PostgreSQL 18.7 update (November 2026). Run by tenant-db-index-sweep.sh once
-- per database, as the superuser; read that script's header first.
--
-- 18.7 fixes bugs that could already have damaged existing data, and the
-- fixes do not repair it. Its release notes ask for:
--
--   gin          GIN indexes, after several fixes for corruption that made
--                queries miss rows or return unrelated ones.
--   trgm_gist    GiST indexes built with pg_trgm's gist_trgm_ops: searches
--                could miss matching rows.
--   bpchar       B-tree indexes on `bpchar` with no length: deduplication could
--                give wrong index-only scan results. `char(n)` is not affected.
--                An expression column's type modifier is not recorded, so
--                expression indexes on bpchar are listed too.
--   no_inherit   NOT NULL NO INHERIT constraints on partitioned tables, which
--                let NULLs into partitions. Reported only: whether to drop the
--                constraint or repair it (ALTER CONSTRAINT ... INHERIT, which
--                fails if a partition already holds NULLs) is the tenant's
--                schema decision.
--
-- Psql variables:
--   reindex   'on' to rebuild the listed indexes with REINDEX INDEX
--             CONCURRENTLY (no lock that blocks the tenant's reads or writes).
--             Anything else lists them only.

\set ON_ERROR_STOP on
\pset footer off

-- Every flagged index, one row per index. Leaf indexes only (relkind 'i'): a
-- partitioned index has no storage of its own, and each of its partitions'
-- indexes is listed separately.
CREATE TEMP VIEW sweep_indexes AS
SELECT DISTINCT ON (ic.oid)
       CASE
           WHEN am.amname = 'gin' THEN 'gin'
           WHEN am.amname = 'gist' AND opc.opcname = 'gist_trgm_ops' THEN 'trgm_gist'
           ELSE 'bpchar'
       END                                        AS kind,
       format('%I.%I', n.nspname, ic.relname)     AS index_name,
       format('%I.%I', tn.nspname, tc.relname)    AS table_name,
       pg_size_pretty(pg_relation_size(ic.oid))   AS size
  FROM pg_index i
  JOIN pg_class ic      ON ic.oid = i.indexrelid AND ic.relkind = 'i'
  JOIN pg_namespace n   ON n.oid = ic.relnamespace
  JOIN pg_class tc      ON tc.oid = i.indrelid
  JOIN pg_namespace tn  ON tn.oid = tc.relnamespace
  JOIN pg_am am         ON am.oid = ic.relam
  -- indclass covers key columns only; INCLUDE columns come out with a NULL
  -- opclass and match nothing below.
  CROSS JOIN LATERAL unnest(i.indclass::oid[], i.indkey::int2[]) AS k(opclass, attnum)
  LEFT JOIN pg_opclass opc ON opc.oid = k.opclass
  LEFT JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
 WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
   AND n.nspname NOT LIKE 'pg\_toast%'
   AND (    am.amname = 'gin'
        OR (am.amname = 'gist'  AND opc.opcname = 'gist_trgm_ops')
        OR (am.amname = 'btree' AND opc.opcintype = 'bpchar'::regtype
            -- attnum 0 is an expression column: its typmod is not recorded.
            AND (k.attnum = 0 OR a.atttypmod = -1)))
 ORDER BY ic.oid, kind;

SELECT current_database() AS database, kind, index_name, table_name, size
  FROM sweep_indexes
 ORDER BY kind, index_name;

SELECT current_database()          AS database,
       'no_inherit'                AS kind,
       conrelid::regclass          AS partitioned_table,
       conname                     AS constraint_name
  FROM pg_constraint
 WHERE contype = 'n' AND connoinherit
   AND conrelid IN (SELECT oid FROM pg_class WHERE relkind = 'p')
 ORDER BY 3, 4;

\if :{?reindex}
\else
\set reindex off
\endif

SELECT :'reindex' = 'on' AS do_reindex \gset

\if :do_reindex
-- Rebuilding on a server that still has the bugs would rebuild into them.
SELECT current_setting('server_version_num')::int >= 180007 AS fixed_server \gset
\if :fixed_server
-- One failed rebuild should not stop the rest: report it and carry on. A failed
-- REINDEX CONCURRENTLY leaves an invalid `<name>_ccnew` index behind, listed
-- below so it can be dropped by hand.
\set ON_ERROR_STOP off
\set ECHO queries
SELECT format('REINDEX INDEX CONCURRENTLY %s', index_name)
  FROM sweep_indexes
 ORDER BY index_name \gexec
\set ECHO none
\set ON_ERROR_STOP on

SELECT current_database() AS database,
       'invalid_after_reindex' AS kind,
       i.indexrelid::regclass AS index_name
  FROM pg_index i
  JOIN pg_class c ON c.oid = i.indexrelid
 WHERE NOT i.indisvalid AND c.relname LIKE '%\_ccnew%';
\else
\echo 'refusing to reindex: server is older than 18.7, so the rebuilt indexes could be damaged again'
\quit
\endif
\endif
