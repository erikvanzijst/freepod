## Context

See proposal.md § Why. The specs are
[bucket-credentials-api](specs/bucket-credentials-api/spec.md),
[cli-bucket-status](specs/cli-bucket-status/spec.md) and
[cli-bucket-objects](specs/cli-bucket-objects/spec.md).

Facts that shape the approach:

1. **The platform does not store the bucket secret.** `ensure_object_storage` reads it back
   from Garage (`GetKeyInfo` with `showSecretKey`) on every reconcile and writes it into the
   namespace Secret. Garage is the only record of it.
2. **Every authenticated Garage admin call costs about 45 ms of Garage CPU** (Argon2 token
   verification), which puts a ceiling of about 20 calls per second on each environment's
   instance. That ceiling is shared with the reconciler and the bucket size exporter.
3. **The public S3 endpoint is the one the pod uses.** `settings.s3_endpoint_url` and
   `settings.s3_region` are projected into the chart as `AWS_ENDPOINT_URL` and the region,
   path-style, behind the platform's wildcard certificate.
4. **Garage behavior, probed against a local `dxflrs/garage:v2.3.0`** (the version
   deployed):
   - Keys are stored verbatim: `../../../../escape.txt` and `foo/bar/../quux/file.txt` were
     both accepted.
   - A key written as `/leading/slash.txt` was stored as `leading/slash.txt`.
   - `CopyObject` shares data blocks: a 20 MiB object and its copy left the data directory
     at about 20 MiB.
   - `CopyObject` does not check the bucket's `maxSize` quota, where `PutObject` does.
   - The S3 compatibility reference lists `DeleteObjects`, `UploadPartCopy`, `CopyObject`,
     `ListObjectsV2`, `AbortMultipartUpload`, `HeadObject` and presigned URLs as
     implemented.
5. **`aws s3` CLI behavior, probed against the same instance**, which these commands
   follow wherever there was a choice:
   - A recursive download normalizes keys and skips any that escape the destination, with
     "File references a parent directory."
   - A file/directory conflict fails that one key, mid-run.
   - `mv` is `HeadObject` + `CopyObject` + `DeleteObject`.
6. **The edge's 60-second read timeout** (Traefik's default) severs a request whose body
   takes longer than that to arrive. Fixing it is out of scope.

## Goals / Non-Goals

**Goals:**

- The owner can reach their bucket from their own machine with the same credentials and
  endpoint their app uses.
- Transfers are as safe as `aws s3`'s where they meet tenant-controlled keys, and no worse
  when interrupted.
- The client keeps its small dependency set and its Python 3.9 floor.

**Non-Goals:**

- Key rotation, short-lived keys, or per-user keys.
- A sync command, globbing, include/exclude filters, or resumable transfers across runs.
- Public-read buckets or website hosting.
- A UI panel.
- Fixing Garage's `CopyObject` quota gap or the edge timeout.

## Decisions

### D1. The owner gets the pod's own key

The endpoint returns the `app-<deployment-id>` key the pod already holds. No new key is
minted.

**Alternative: a short-lived key per CLI run.** Garage v2 supports this (`UpdateKey` takes
`expiration`). It was rejected for three reasons:

- The read becomes a write.
- Expired keys remain in Garage (`GetKeyInfo` reports `expired`), so they need a sweep.
- Teardown deletes only `app-<id>` before it sets the expiry lifecycle rule. Any other key
  alive at deletion could remove that rule, which is exactly the race teardown's ordering
  closes. Adopting short-lived keys later means teardown must revoke every key granted on
  the bucket first.

**Cost:** a leaked copy is valid for the deployment's life, because rotation does not exist.
This is accepted on the same grounds as the database password:

- It goes to the owner alone.
- The client never writes it to disk.
- Behavior can be tightened later without changing these commands.

### D2. The secret is read from Garage per request, not stored by the platform

The secret stays where it lives today. Storing it encrypted (as `deployment_database` stores
the database password) would save one admin call per request, at the cost of a second copy
the reconciler must keep in step with Garage.

The read path is:

- **Owner:** one `GetKeyInfo?search=app-<id>&showSecretKey=true`, which returns the access
  key id and the secret together. That replaces `find_key`'s `ListKeys` scan, which grows
  with every deployment's key.
  - `search` matches "partial key ID or name". Every `app-` name is the same length and
    unique, and key IDs start with `GK`, so the only possible match is the key itself.
    The service still checks the returned name before trusting it.
  - A missing key answers 404, which is told apart from an unhealthy store by status
    alone.
- **Administrator:** the same lookup without `showSecretKey`, so the secret is never
  requested from Garage at all.
- **Usage, when requested:** one `GetBucketInfo` by global alias, returning `bytes`,
  `objects` and the bucket's `quotas`.

A product that does not opt in is answered from the template alone, with no Garage call.

### D3. Usage is live, and opt-out

The database endpoint reports a swept figure, because measuring a database is a query on a
shared cluster. A bucket's size is a single `GetBucketInfo` that Garage maintains as a
counter, so the endpoint reads it live.

`?usage=false` exists because the object commands call the endpoint on every run, and two
admin calls per `ls` would double their load on the shared ceiling. Usage, with the limits
the bucket carries, is one nested `usage` object that is `null` when not requested. That is
how "not requested" stays distinguishable from zero.

Response fields:

- `bucket`
- `endpoint`
- `region`
- `access_key_id`
- `secret_access_key`, nullable
- `secret_withheld`
- `usage`, nullable: `bytes`, `objects`, `max_size_bytes`, `max_objects`

The stable no-bucket code is `object_storage_unavailable`. The exception class mirrors
`RelationalStorageUnavailableException`.

### D4. A small S3 client of our own, over httpx

boto3 brings botocore, tens of megabytes, into a client whose runtime dependencies are
click, httpx and pathspec. The client only ever talks to one implementation (Garage, path
style), using the operations these commands need:

- `ListObjectsV2`, `HeadObject`, `GetObject`, `PutObject`
- the multipart set: create, upload part, complete, abort
- `CopyObject` and `UploadPartCopy`
- `DeleteObject` and `DeleteObjects`
- query-string presigning

It is a module of a few hundred lines with these parts:

- a SigV4 signer, tested against AWS's published signing test vectors;
- an S3 error-XML parser, so that Garage's codes map to the owner-facing messages in the
  spec (quota refusal → "bucket full", `RequestTimeTooSkewed` → clock);
- an integration test suite against a throwaway `dxflrs/garage:v2.3.0` container, skipped
  when Docker is unavailable.

### D5. Payloads are signed, in bounded parts

Every request body is hashed and its SHA-256 signed (`x-amz-content-sha256`), so Garage
refuses a body that differs from what the client read. That is the spec's integrity
requirement, met without a separate checksum.

- **Small files:** up to the 8 MiB threshold, the file is read into memory and sent in one
  `PutObject`.
- **Larger files:** a multipart upload with 8 MiB parts. The part size grows only when a
  file would otherwise exceed S3's 10,000-part limit (that happens above about 78 GiB).
- **Concurrency:** up to four parts, or four small files during a recursive copy, are in
  flight at once, which bounds memory at about 32 MiB.

8 MiB is a deliberate trade against the edge timeout (Context 6): a part takes about 60 s
at about 1.1 Mbit/s, so a smaller part survives slower uplinks than the 16 MiB parts a
throughput-first default would use. It is above S3's 5 MiB minimum part size.

On any failure, and on `KeyboardInterrupt`, the client sends `AbortMultipartUpload` before
exiting. Parts left by a client killed outright are reclaimed by the bucket's
`AbortIncompleteMultipartUpload` lifecycle rule.

### D6. Resolving a remote path: object first, then prefix

A remote path without a trailing `/` is resolved as follows:

1. `HeadObject` on the exact key. If it exists, the path names that object.
2. Otherwise `ListObjectsV2` on `key/` with `max-keys=1`. If anything is there, the path
   names that prefix.
3. Otherwise the path does not exist.

A trailing `/` skips step 1. The root never needs resolving.

This is what gives `cp :x` the spec's object-first rule. It also lets `rm :uploads` refuse
a prefix without `-r` before deleting anything.

Destinations are not resolved. `cp f :name` writes the key `name` even when `name/` holds
objects, as `aws s3 cp` does. That keeps an upload to one key at one request, and the
trailing slash is how a user says "into".

The leading `/` is stripped after the marker (Context 4: Garage cannot store it anyway), so
`:/app/x` reads the way `freepod cp :/app/x` does.

### D7. Making keys safe as local paths, without listing first

Each key from a recursive download is handled as soon as it is listed:

1. The key is split on `/`; empty and `.` segments are dropped and `..` segments are
   resolved.
2. If the result is empty, or it climbs above the destination, the key is skipped and
   reported.
3. The resulting path is joined under the destination and checked again with
   `os.path.realpath`, so an existing symlink inside the destination cannot redirect it.
4. A set of local paths already written in this run catches two keys that normalize to the
   same file. The filesystem's own refusal catches a file/directory conflict.

Both cases are skipped and reported, and the run exits non-zero at the end.

**Alternative: list the whole source first and refuse up front.** Rejected: a large tree
would sit silent for the whole listing before transferring a byte, which is presumably why
`aws s3` does not do it either. The in-run set costs memory proportional to the keys
copied, which a listing-first approach would spend anyway.

Downloads stream to a temporary file in the destination's directory, then
`os.replace`, so a reader never sees a truncated file. The received length is checked
against `Content-Length`. For a single-part object, whose ETag is a plain MD5, the MD5 is
checked too.

### D8. `mv` and copies within the bucket stay inside Garage

A copy within the bucket is `CopyObject` per object, or `UploadPartCopy` parts above 5 GiB,
the S3 limit for a single copy. Whether Garage enforces that limit is settled by the
integration tests; the client uses the multipart path above it regardless. Garage shares the
blocks, so even a large copy costs metadata, not disk (Context 4).

`mv` is that copy, or a transfer for local↔remote, followed by deleting the source:

- **Within the bucket:** source objects are deleted with `DeleteObjects` in batches of up
  to 1000, each batch only after every copy in it has succeeded.
- **Upload:** local files are unlinked one by one after their upload completes, and
  directories left empty are removed bottom-up.
- **Download:** objects are deleted after their temporary file has been moved into place.

A move onto its own source is refused. A move into its own subtree within the bucket
(`mv :a :a/b`) is refused, because the listing would pick up its own output.

**Not atomic.** A failure between copy and delete leaves both. The spec makes that a
reported, non-zero outcome rather than hiding it.

**`CopyObject` ignores the size quota** (Context 4), so copies and moves within the bucket
never fail on quota. That is a pre-existing gap reachable by any tenant key. It is
inherited, not introduced, and is left out of scope.

### D9. `rm` alone requires `-r`

`cp` and `mv` recurse unasked, to match `freepod cp`. `rm` requires `-r` for a prefix,
including the root: deletion is the one irreversible operation and the bucket has no
versioning. `aws s3 rm` and Unix `rm` both require it.

`rm -r` lists the prefix and deletes in `DeleteObjects` batches as it goes. A missing
single key is detected by D6's resolution, because `DeleteObject` itself succeeds silently
on a missing key.

### D10. `link` presigns on the client

The URL is signed with the owner's key on the client: no platform round trip, and no new
API surface.

- The 7-day maximum is SigV4's own limit for query-string signatures.
- A presigned URL authenticates as the key that signed it, so every link stops working when
  the deployment is deleted and its key revoked. That bounds a forgotten link to the
  deployment's life or its expiry, whichever comes first.
- `--expires` accepts `<n>s`, `<n>m`, `<n>h` and `<n>d`.
- A GET link is preceded by a `HeadObject`, so that a mistyped key is refused rather than
  printed as a URL that answers 404.

### D11. Credentials are fetched every run and kept in memory only

Caching them on disk would put a live read/write credential next to the session tokens,
for a saving of one API call per command.

The cost is one platform request and one Garage admin call per command. A script calling
`freepod bucket cat` in a tight loop spends Garage's shared admin budget at about 45 ms per
iteration. That is acceptable at today's scale and is noted as a risk below.

`--verbose` request logging must redact the `Authorization` header and the
`X-Amz-Signature` / `X-Amz-Credential` query parameters of S3 requests.

### D12. Naming

The pieces are named to match their `db` counterparts (`/database`, `freepod db`,
`caelus get-deployment-database`):

- `freepod bucket`
- `/bucket`
- `caelus get-deployment-bucket`

`object`/`relational` read awkwardly in a UI, and the UI panel will follow these names.

### D13. Local inputs

A recursive upload walks the directory with these rules:

- It follows symlinks to files.
- It does not descend into symlinked directories. It reports them as skipped, which rules
  out cycles and keeps the upload inside the tree the user named.
- Empty directories produce nothing.
- Keys are built with `/` on every platform.

## Risks / Trade-offs

- **A leaked secret is valid until rotation exists.**
  → It goes to the owner only, is never stored by the client, and is masked in `status`.
  Rotation is follow-up work, and teardown already revokes it on delete.
- **Per-command admin calls on Garage's shared ceiling** (about 20/s per environment).
  → `usage=false` halves it for object commands, and the administrator path skips the
  secret read. If scripted use proves heavy: an in-process cache per invocation is already
  the design, and a short-lived cache in the API is the next step, not a client cache.
- **Slow uplinks can still hit the edge's 60 s read timeout on an 8 MiB part.**
  → A failed part is retried once before the upload is aborted. Raising the timeout is
  tracked separately.
- **Collisions are found mid-run, not up front.**
  → Reported per key, with a non-zero exit. This is the trade the user chose over a silent
  pause before large transfers.
- **`mv` is not atomic.**
  → The source is deleted only after its copy succeeds, so a failure leaves a duplicate,
  never a loss.
- **Our own SigV4 implementation could have edge-case bugs** (encoding of unusual keys).
  → AWS test vectors, plus integration tests against Garage with keys containing spaces,
  `+`, `%`, unicode and `//`.

## Migration Plan

Additive. Deploy the API first; a client released before it would get FastAPI's bare 404
for the missing route. Then publish the client with a minor version bump. No data migration,
no chart change, no reconcile.

Rollback: remove the client commands in a later release. The endpoint is read-only and can
stay or go independently.
