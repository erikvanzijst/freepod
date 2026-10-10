## 1. API read model and service

- [x] 1.1 Add the `DeploymentBucketRead` read model (design.md § D3): `bucket`, `endpoint`,
      `region`, `access_key_id`, nullable `secret_access_key`, `secret_withheld`, and a
      nullable `usage` object with `bytes`, `objects`, `max_size_bytes` and `max_objects`.
      Verify by unit test that no field carries Garage's internal bucket id or a composed URL.
- [x] 1.2 Add `ObjectStorageUnavailableException` with `code = "object_storage_unavailable"`,
      mirroring `RelationalStorageUnavailableException`, and verify the API's error handler
      emits the code on a 404.
- [x] 1.3 Add a Garage client method that looks a key up with
      `GetKeyInfo?search=<name>`, with `showSecretKey` optional, returning `None` on 404 and
      raising on any other failure, and checking that the returned name matches exactly
      (design.md § D2). Verify by unit test with a stubbed transport for found, missing,
      mismatched name and a 5xx error.
- [x] 1.4 Add a Garage client method reading `GetBucketInfo?globalAlias=`, returning
      `bytes`, `objects` and `quotas`. Verify by unit test.
- [x] 1.5 Implement `get_bucket_details` in `app/services/object_storage.py`, reached
      through `get_deployment_orm` so missing, not-yours and deleted answer as everywhere
      else:
      - a product that does not opt in raises the unavailable exception without any Garage
        call;
      - a missing key or bucket raises the unavailable exception;
      - the secret is requested from Garage only when the viewer is the owner;
      - usage is read only when asked;
      - endpoint and region come from `settings.s3_endpoint_url` / `s3_region`.

      Verify by unit tests covering owner, administrator, not-opted-in (asserting zero Garage
      calls), not provisioned, `usage=False` (asserting no `GetBucketInfo`), and Garage
      unreachable (a server error, not the unavailable code).
- [x] 1.6 Verify reading has no side effects: a test asserting the service issues only
      read calls (`GetKeyInfo`, `GetBucketInfo`) and none that create, update, allow or
      delete.
- [x] 1.7 Verify the secret never reaches a log: capture logs across a successful owner
      read and a failure raised after the secret was fetched, and assert the secret appears
      in no record.

## 2. Endpoint and operator CLI

- [x] 2.1 Add `GET /api/users/{user_id}/deployments/{deployment_id}/bucket` in
      `api/app/api/users.py` beside `/database`, with a `usage: bool = True` query parameter,
      `require_self` authorization, and a docstring covering:
      - the owner-only secret, and why;
      - live usage and the opt-out, and why;
      - the absence code.

      Verify by API tests: owner, administrator (secret null and `secret_withheld` true), a
      non-owner refused with 403, a deleted deployment answering the standard 404, the
      unavailable code, and `usage=false`.
- [x] 2.2 Add `caelus get-deployment-bucket <user_id> <deployment_id>` over the same service,
      withholding the secret from an operator who is not the owner, and verify with a CLI
      test.
- [x] 2.3 Document the endpoint in `api/README.md` beside the database endpoint, and verify
      the README's endpoint list includes it.

## 3. Client S3 module

- [x] 3.1 Add `cli/src/freepod/s3.py` with a SigV4 header signer and a query-string
      presigner, signing each body's SHA-256 (design.md § D4, D5). Verify against AWS's
      published SigV4 test vectors, and against keys containing spaces, `+`, `%`, `//`,
      unicode and a leading `.`.
- [x] 3.2 Add the operations from design.md § D4, path-style:
      - `ListObjectsV2` with delimiter and continuation;
      - `HeadObject`, streaming `GetObject` and `PutObject`;
      - the multipart set;
      - `CopyObject` and `UploadPartCopy`;
      - `DeleteObject` and batched `DeleteObjects`.

      Verify each with unit tests over a stubbed `httpx` transport.
- [x] 3.3 Parse S3 error XML into a client exception carrying the code and message, mapping
      Garage's quota refusal to "the bucket is full" and `RequestTimeTooSkewed` to a clock
      message. Verify with recorded Garage error bodies, including the quota text observed
      on v2.3.0.
- [x] 3.4 Redact S3 credentials in `--verbose` output: the `Authorization` header, and the
      `X-Amz-Credential` and `X-Amz-Signature` query parameters. Verify that a verbose run's
      captured stderr contains neither the secret nor a signature.
- [x] 3.5 Add an integration suite against a throwaway `dxflrs/garage:v2.3.0` container,
      skipped when Docker is unavailable. It covers:
      - a round trip of single and multipart uploads;
      - a tampered payload hash being refused;
      - `CopyObject` and `UploadPartCopy`, including whether a copy above 5 GiB is refused;
      - `DeleteObjects`;
      - presigned GET and PUT fetched with no credentials.

      Verify it passes locally.

## 4. `freepod bucket status`

- [x] 4.1 Add `cli/src/freepod/bucket.py` with `read(api, user_id, deployment_id, usage=True)`,
      returning `None` for the `object_storage_unavailable` code and raising on any other
      404, as `database.read` does. Verify with tests mirroring `test_database.py`.
- [x] 4.2 Add the `bucket` group and `status` subcommand in `cli.py`, resolving the
      deployment with `_project_deployment`. Render the bucket, endpoint, region, access key
      id, the secret (masked with the fixed-width mask and a `--show-secret` hint), size
      against its limit and objects against theirs. Verify the default output omits the
      secret, `--show-secret` prints it, a withheld secret is stated as such, and a deployment
      without a bucket prints that plainly and exits 0.
- [x] 4.3 Add the group to the surface conventions test (`tests/test_surface.py`) and
      verify `--help`, `--quiet` and the no-color rules hold.

## 5. Remote paths and the read commands

- [x] 5.1 Implement remote-path parsing:
      - the `:` marker, with the leading `/` stripped and `:` / `:/` meaning the root;
      - the optional marker for `ls`, `rm`, `cat` and `link`;
      - for `cp` and `mv`, refusing an invocation with neither side marked before sending
        any request.

      Verify with unit tests over each form in the spec.
- [x] 5.2 Implement object-first resolution (`HeadObject`, then a one-key listing of
      `key/`; a trailing `/` skips the head). Verify against a bucket holding both `x` and
      `x/…`.
- [x] 5.3 Fetch credentials once per invocation with `usage=false`, held in memory only.
      Report a deployment without a bucket, or a withheld secret, as a non-zero refusal
      before any S3 request. Verify that no file under the client's config directory
      changes during an object command.
- [x] 5.4 Implement `ls [-l] [-r] [path]`: one level with `/`-suffixed prefixes, recursive
      relative keys, and size plus last-modified with `-l`. Verify against the spec's
      scenarios, including an empty bucket exiting 0 and a missing path exiting non-zero.
- [x] 5.5 Implement `cat path...`, streaming each object's bytes to stdout in order without
      buffering and refusing a prefix. Verify byte-identical output for a binary object
      larger than memory chunks, and that two objects concatenate in argument order.
- [x] 5.6 Implement `link [--put] [--expires D] path`. Default to a GET link valid for 1 h,
      refuse more than 7 d, `HeadObject` before a GET link, and print only the URL on stdout.
      Verify in the integration suite that both link kinds work without credentials, and by
      unit test that `8d` is refused.

## 6. Transfers

- [x] 6.1 Implement upload: a single signed `PutObject` up to 8 MiB, multipart above it with
      8 MiB parts (grown only past 10,000 parts), four transfers in flight, one retry per
      failed part, and `AbortMultipartUpload` on failure or `KeyboardInterrupt`. Verify in
      the integration suite that a large file round-trips byte-identical, and that an
      interrupted upload leaves no object and no listed multipart upload.
- [x] 6.2 Implement download: a temporary file beside the destination, then `os.replace`,
      checking the length against `Content-Length` and the MD5 against a single-part ETag.
      Verify an interrupted download leaves neither a destination file nor a temporary
      file.
- [x] 6.3 Implement key-to-local-path normalization and containment (design.md § D7):
      - segment normalization;
      - a `realpath` check under the destination;
      - an in-run set of written paths;
      - per-key skip reports;
      - a non-zero exit at the end.

      Verify with the keys probed on Garage: `../../../../escape.txt`,
      `foo/bar/../quux/file.txt`, `./dot/file.txt`, `a//double.txt` beside `a/double.txt`,
      and `plain/a` beside `plain/a/b`.
- [x] 6.4 Implement `cp` with the spec's destination rules for upload, download and
      within-bucket (server-side `CopyObject`, or `UploadPartCopy` above 5 GiB), with
      overwrite and no prompt. Walk local trees following file symlinks, skip symlinked
      directories with a report, upload nothing for empty directories, and build keys with
      `/`. Verify every `cp` scenario in the spec, and that a within-bucket copy transfers
      no object bytes through the client (a stubbed transport asserting no GET or PUT
      bodies).
- [x] 6.5 Implement `mv` as `cp` plus deleting each source only after its copy succeeded:
      - batched `DeleteObjects` within the bucket;
      - unlinking files and pruning emptied directories locally;
      - refusing a move onto itself or into its own subtree;
      - reporting any source left behind, with a non-zero exit.

      Verify the spec's `mv` scenarios, including a forced copy failure leaving its source.
- [x] 6.6 Implement `rm [-r] path...`:
      - an object is deleted;
      - a prefix is refused without `-r`, with a message mentioning `-r`;
      - `-r` deletes in batches as it lists;
      - a missing path exits non-zero.

      Verify each scenario, including that the refusal deletes nothing.
- [x] 6.7 Route progress to stderr only when it is a terminal; let `--quiet` silence
      progress and success messages but never errors or skip reports. Verify with captured
      streams.

## 7. Documentation and end-to-end verification

- [x] 7.1 Update `cli/README.md`'s command table and `cli/DEVELOPMENT.md` with the
      following, keeping internals out of the README:
      - the `bucket` group;
      - the marker and resolution rules;
      - the key-safety rule;
      - why `rm` alone needs `-r`;
      - why credentials are never cached.
- [x] 7.2 Update `cli/src/freepod/assets/SKILL.md`: add `freepod bucket` to the command
      reference, and say in the object-storage section that an agent can inspect and seed
      the bucket from the client while the environment remains how the app reaches it.
      Verify the skill's own drift test passes.
- [x] 7.3 Update `ui/docs/developers/storage/object-storage.mdx` with the commands and a
      short example of each, and verify the docs site builds.
- [x] 7.4 Verify end to end on dev against a real `custom` deployment with object storage:
      - `status` figures match `GetBucketInfo`, and `--show-secret` matches the pod's
        `AWS_SECRET_ACCESS_KEY`;
      - a directory round-trips with `cp` up and `cp` down;
      - a file above the multipart threshold arrives byte-identical;
      - `mv` within the bucket and `rm -r` behave as specified;
      - both link kinds work from `curl`.
- [x] 7.5 Verify against a deployment whose product has no object storage that `status`
      reports no bucket with exit 0 and the object commands exit non-zero.
- [x] 7.6 Confirm the reads changed nothing: the key, the grant, the quota and the
      lifecycle rules are identical before and after 7.4's `status` and endpoint reads,
      and no reconcile was triggered.
