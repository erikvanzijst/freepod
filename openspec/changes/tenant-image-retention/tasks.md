## 1. The retention rule

- [x] 1.1 Add `registry_retained_past_images` (default 2) and `registry_prune_grace_hours` (default 24) to `api/app/config.py` — verify settings construct with neither set
- [x] 1.2 Add `app/services/image_retention.py` computing one owner's retained digests from the ledger: desired + applied + two earlier distinct images per live deployment, matched as `{owner}@sha256:…` string values anywhere in release user values (D1, D2) — verify unit tests cover every scenario under "Retained images are derived from the release ledger" and "Images are matched by value, as owner references"
- [x] 1.3 Add fresh-build retention: builds open, or succeeded within the grace period, keep their image and their tag (D3) — verify tests for a build that just finished, one still pushing, and one never deployed past the grace period
- [x] 1.4 Assert that nothing is persisted: the module only reads — verify a test runs the rule inside a transaction and asserts no row was written

## 2. Write-time check

- [x] 2.1 Reject a create/update naming a build whose image is not retained, with code `image_not_retained`, distinct from "Unknown build" (D8) — verify API tests: rollback within the window accepted, past the window rejected with no release created
- [x] 2.2 Reject a create/update whose user values carry an owner image that is not retained; ignore other owners' references — verify tests: an old image submitted without its build is rejected, a vars-only update is accepted, a retained image reused from another deployment is accepted
- [x] 2.3 Update `_validate_build_reference`'s docstring, the deployment endpoints' OpenAPI descriptions, and the 400 response documentation to describe the retention condition

## 3. Registry capability

- [x] 3.1 Add `registry_tokens.prune_token(settings, owners)`: `pull`+`delete` on exact `u/{owner}` names, TTL at most an hour, refusing non-exact names (D7) — verify unit tests assert no push, no cache repository, no catalog, and the TTL bound
- [x] 3.2 Integration test against `registry:3.1.1` with token auth: the prune token deletes a tag in a repository it names; it is refused for push, for another owner, for `cache/{owner}` and for the catalog; a build capability is refused deletion

## 4. The prune

- [x] 4.1 Add `caelus registry-prune [--dry-run]`: per owner with builds, list tags and resolve digests, then compute retention, then delete tags outside it, by tag, never by digest (D4, D5) — verify tests with a fake registry: two tags on one retained digest both survive; a tag with no build row is judged by digest; a tag whose build is running is kept
- [x] 4.2 Dry-run report per owner: tags removed, tags kept with reason (D9) — verify a test asserts the dry run issues no DELETE
- [x] 4.3 Make failures independent per tag and per owner, and exit non-zero if any failed — verify a test where one deletion fails still deletes the rest and exits non-zero

## 5. Infrastructure

- [x] 5.1 Add the `registry-prune` CronJob to `tf/app/caelus` at `0 3 * * *`, API image, the build worker's database and signing-key Secrets, `concurrencyPolicy: Forbid`, an active deadline (D6) — verify `terraform plan` in both workspaces adds only the CronJob
- [x] 5.2 Update `tf/app/README.md`'s registry section and `products/custom/builder/README.md`'s note on tags to state that tags outside retention are removed nightly, linking the `tenant-image-retention` spec

## 6. Rollout

- [x] 6.1 Run the full `api/` test suite — verify green
- [x] 6.2 Deploy the API to dev, run `caelus registry-prune --dry-run` in the API pod, and confirm every deployment's applied and desired image is listed as kept
- [x] 6.3 Apply the CronJob to dev, trigger it once by hand, then restart the registry to collect — verify the registry volume shrinks and every dev custom deployment still pulls (restart one pod)
- [ ] 6.4 Repeat 6.2–6.3 for prod
