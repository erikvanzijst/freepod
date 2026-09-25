## 1. Data model and migration

- [ ] 1.1 Replace `BuildORM.user_id` with `deployment_id` (a `NOT NULL` foreign key to `deployment`, indexed, no cascade) and update `BuildRead` and the other build schemas; verify `tests/test_schema_drift.py` passes once the migration exists
- [ ] 1.2 Write the migration: refuse with a clear message if any build is `queued` or `running`; add a nullable `deployment_id`; backfill by release `build_id`, then by release image, taking the earliest matching release (design D2); delete unlinked builds; set `NOT NULL`; drop `user_id`. Verify with a migration test in a throwaway schema covering each backfill path, the earliest-release tiebreak, deletion of unlinked builds, and the in-flight refusal
- [ ] 1.3 Write the downgrade (re-add `user_id` filled from the build's deployment, drop `deployment_id`) and verify an upgrade → downgrade round trip in the migration test
- [ ] 1.4 Dry-run the backfill as a read-only query against dev and prod, and verify the counts match design.md's table (dev 18 and prod 16 deleted), recording any drift in design.md before applying

## 2. Build service and API

- [ ] 2.1 Scope build creation, listing and reads by deployment in `app/services/builds.py`: resolve the deployment under its owner, refuse a `deleting` or `deleted` one, and derive the owner from it for the artifact check. Verify with service tests for each refusal and for reads of a deleted deployment's builds
- [ ] 2.2 Return an in-flight build only to its own deployment and refuse with 409 when it belongs to another (design D8); verify with a test that submits one artifact for two deployments
- [ ] 2.3 Move every build route to `/users/{user_id}/deployments/{deployment_id}/builds` in `app/api/builds.py` and delete the account-level routes; verify with API tests that the old paths return 404, a build under the wrong deployment is not found, and a non-owner is refused
- [ ] 2.4 Update the build worker and `build_jobs.py` to read the owner through the deployment for the artifact key, image repository and push capability; verify `tests/test_build_worker.py` and the job manifest tests pass
- [ ] 2.5 Update artifact and endpoint docstrings that name the old build path (e.g. `app/api/artifacts.py`); verify with `grep -rn '/builds' api/app` showing only nested paths

## 3. Release validation

- [ ] 3.1 Require a named build to belong to the deployment being updated, and refuse a creation request that names a build (spec `deployment-release-ledger`); verify with tests for another deployment's build, a nonexistent build, a build named on creation, and an image reused with no build

## 4. freepod CLI

- [ ] 4.1 Reorder `deploy.py` for a project with no pointer or with `--recreate`: create the deployment with no image or build, save the pointer immediately, then pack, upload, build and release, reusing the existing wait-for-ready. Verify with `tests/test_deploy.py` cases for a first deploy, recreate, and a failed first build that leaves the pointer and names `freepod delete`
- [ ] 4.2 Create builds and follow their logs under the deployment's path in `build.py`; verify with `tests/test_build.py`
- [ ] 4.3 Make `freepod builds` list only the project's deployment's builds and refuse outside a project, for another environment, or before a first deploy; verify with `tests/test_builds.py`, including a deleted deployment still listing its builds
- [ ] 4.4 Update the CLI README, the bundled skill (`assets/SKILL.md`) and help text that describe build-first ordering or the account-wide history; verify with `grep -rni "account's builds\|build first" cli/`
- [ ] Bump the freepod cli version

## 5. Documentation

- [ ] 5.1 Update AGENTS.md's builds bullet ("owned by a user… addressed under their owner") to say builds belong to a deployment; verify by reading it back
- [ ] 5.2 Update the `products/custom` README where it describes the first deploy; verify by reading it back

## 6. Rollout verification

- [ ] 6.1 Run the full API and CLI test suites and verify both pass
- [ ] 6.2 After deploying to dev: verify every build row has a deployment, `freepod builds` in a project lists only its own builds, and `freepod deploy` in a new directory shows the placeholder and then the built app
