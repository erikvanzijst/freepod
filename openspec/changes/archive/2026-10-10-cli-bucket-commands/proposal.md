## Why

A storage-enabled deployment gets a private Garage bucket and an access key that only its
pod ever sees. The owner cannot list what their app has stored, seed it with files, pull a
backup down, or check how close it is to the quota without writing and deploying code to do
it. `freepod db` already answers the same questions for the database; the bucket has no
counterpart.

Unlike the database, the bucket needs no tunnel. Its S3 endpoint is already public at
`blob.<environment domain>`, authenticated by SigV4 rather than by the platform's session
layer, and built to carry multipart uploads and presigned URLs from outside the cluster. A
client holding the bucket's credentials can talk to it directly, so what is missing is a way
for the owner to get them, and commands that use them.

## What Changes

- A **deployment-scoped read endpoint**, `GET /api/users/{user_id}/deployments/{deployment_id}/bucket`,
  returning the bucket's name, the S3 endpoint and region, the access key id and secret, and
  by default its live usage: bytes and object count against the plan's size and object
  limits. `?usage=false` skips the usage read for callers that only need credentials.
- The secret goes to the **owner alone**, as with the database password: an administrator
  receives everything else and is told it was withheld.
- Absence follows the database endpoint: a stable not-found code for a deployment with no
  bucket, and the platform's standard not-found for one that is missing, not yours or
  deleted.
- A **`freepod bucket` command group** in the end-user client, talking to the bucket
  directly over S3 with credentials it fetches from the endpoint on every run and never
  writes to disk:
  - `status` — the bucket's identity, credentials (secret masked unless `--show-secret`) and
    usage.
  - `ls [-l] [-r]` — list a prefix, or the whole tree.
  - `cp` — copy between the local machine and the bucket, or within the bucket. A directory
    or prefix source is copied recursively with no flag, as `freepod cp` does.
  - `mv` — the same paths as `cp`, removing the source once the copy is complete. Within the
    bucket it is a server-side copy and delete; no object's bytes pass through the client.
  - `rm [-r]` — delete an object, or a prefix with `-r`.
  - `cat` — stream objects to stdout as-is.
  - `link [--put] [--expires]` — print a presigned GET (default) or PUT URL, valid for 1 hour
    by default and at most 7 days.
- Large uploads always go up in parts; an interrupted one is aborted rather than left
  holding disk.
- Downloads normalize each key into a local path, and skip, with a warning and a non-zero
  exit, any key that would land outside the destination.
- `caelus get-deployment-bucket`, the operator CLI's read over the same service.

## Capabilities

### New Capabilities

- `bucket-credentials-api`: the deployment-scoped bucket endpoint, what it returns, its
  optional live usage, its absence semantics, and who may read the secret.
- `cli-bucket-status`: the `freepod bucket` group and `bucket status` — what it reports and
  how it masks the secret.
- `cli-bucket-objects`: the object commands `ls`, `cp`, `mv`, `rm`, `cat` and `link` — how
  they name remote paths, how directories and prefixes map onto each other, how keys are
  made safe as local paths, and how large and interrupted transfers behave.

### Modified Capabilities

None. Provisioning, the key's single-bucket grant, quotas and teardown are unchanged. The
access key the pod already holds is the one the owner is given; no new key is minted.

## Impact

**API**

- A new read endpoint beside `/database`, with a read model and a service function shared
  with `caelus`. The secret is read from Garage (`GetKeyInfo`) at request time, as
  provisioning already does, and only for the owner; usage is one `GetBucketInfo`. Each is
  an authenticated Garage admin call, and those are expensive (Argon2 token verification),
  which is why usage can be skipped.

**Client**

- A new `bucket` command group in `cli/`, with a small S3 client of its own: SigV4 signing
  and presigning over the existing `httpx` dependency, covering only the operations these
  commands use. No new runtime dependency; the Python 3.9 floor is unchanged.

**Docs**

- `cli/README.md`, `cli/DEVELOPMENT.md`, `api/README.md`, the agent skill
  (`cli/src/freepod/assets/SKILL.md`) and the docs portal's
  `developers/storage/object-storage.mdx`.

**Not affected**

- No chart, reconciler, Terraform or edge change. The edge's 60-second read timeout, which
  can sever a slow request, is a separate edge fix. Uploading in parts keeps each request
  bounded, but a part on a slow enough uplink can still exceed it until that fix lands.
- No UI panel; that is later work.
- Key rotation does not exist and is not added. Handing the pod's key to the owner means a
  leaked copy stays valid until rotation exists; see design.md.
