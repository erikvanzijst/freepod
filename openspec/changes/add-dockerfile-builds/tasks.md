## 1. Builder selection

- [ ] 1.1 Add a `select_builder(source)` helper to `products/custom/builder/build.py`
      returning which builder applies, decided solely by a regular file named
      `Dockerfile` at the extracted project's root; verify with unit tests covering a
      project with one, without one, and with a `Dockerfile` in a subdirectory only (the
      last selects detection).
- [ ] 1.2 Log the chosen builder as the first line of the build's own output, naming the
      Dockerfile path or the fact that detection will run; verify by asserting on the
      captured output in a unit test for both branches.
- [ ] 1.3 Branch `main()` between the two paths so extraction, cache refs, metadata file
      and termination message stay shared; verify the existing builder-script tests still
      pass unchanged for the detection path.

## 2. The Dockerfile build

- [ ] 2.1 Add `build_and_push_dockerfile(...)` invoking `buildctl-daemonless.sh` with
      `--frontend=dockerfile.v0`, `--opt filename=Dockerfile`, `--local context=<source>`
      and `--local dockerfile=<source>`; verify with a test capturing the argv that the
      frontend, filename and both local mounts are exactly these.
- [ ] 2.2 Pin the Dockerfile frontend: add a module constant naming the mirrored image by
      digest and pass it as `--opt build-arg:BUILDKIT_SYNTAX=<ref>`; verify with a test
      that the constant carries an `@sha256:` digest (mirroring the existing
      `test_the_frontend_image_is_pinned_by_digest`) and that the build arg reaches argv.
- [ ] 2.3 Mirror the frontend image into the internal registry from
      `scripts/mirror-railpack-images.sh` and extend its digest verification step to cover
      it; verify by running the script and confirming the mirrored digest equals the
      constant in `build.py`.
- [ ] 2.4 Confirm a project's `# syntax=` directive has no effect; verify with an
      end-to-end build of a Dockerfile whose directive names a non-existent frontend,
      asserting the build succeeds and that name is never resolved.
- [ ] 2.5 Carry the unchanged import/export cache, image output, metadata-file and
      `--progress=plain` arguments across from the Railpack path, and confirm no
      `build-arg:cache-key` and no `--allow` reach the Dockerfile invocation; verify by
      asserting the cache ref and output arguments match the Railpack path's and that
      neither string is present.
- [ ] 2.6 Confirm a failed Dockerfile build raises `BuildFailure` and publishes nothing,
      with no fallback to detection; verify with a test that stubs a non-zero `buildctl`
      and asserts the failure propagates and `prepare_plan` was never called.

## 3. The post-push contract check

- [ ] 3.1 Add the platform port as a module constant in `build.py` whose comment names
      `products/custom/chart/values.yaml` as the value it mirrors; verify by test that the
      constant equals the chart's `containerPort`, so the two cannot drift silently.
- [ ] 3.2 Add an image-config reader that fetches the manifest and config blob from the
      registry by digest with TLS verification disabled; verify with a test against a
      stubbed HTTP layer that it returns `ExposedPorts`, `Entrypoint` and `Cmd`, and that
      any error is swallowed into "could not inspect" rather than raised.
- [ ] 3.3 Emit a warning when the platform port is not among the image's declared ports
      and when the image declares neither entrypoint nor command, wording both as *may*
      not serve; verify with tests over the three spec scenarios — non-matching port,
      no command, conforming image — asserting the build succeeds in all three.
- [ ] 3.4 Run the check on both builder paths, not only the Dockerfile one, since a
      detected image can also fail the contract; verify by asserting the warning fires for
      a Railpack-path build whose stubbed config declares the wrong port.

## 4. Documentation

- [ ] 4.1 Update `products/custom/builder/README.md` with the precedence rule, the absence
      of fallback and of build arguments, the unchanged `$PORT` contract, the pinned
      frontend and why `# syntax=` is overridden, and the accepted risk of Docker Hub base
      images; verify the environment-contract table and the new prose agree with what
      `build.py` does.
- [ ] 4.2 Update `cli/src/freepod/assets/SKILL.md` so a root Dockerfile is described as
      taking over the build — today it reads as though Dockerfiles are merely unnecessary
      — including that `railpack.json` and `Procfile` stop applying and that a
      `# syntax=` directive is ignored, and cross-reference the build-variables section;
      verify `cd cli && uv run pytest tests/test_skill.py`
      passes and the frontmatter description still fits on one line.
- [ ] 4.3 Bump `cli/src/freepod/__init__.py` `__version__`; verify `cd cli && uv run
      pytest` passes, and note in the change that shipping it needs a `freepod-v*` tag.

## 5. Release

- [ ] 5.1 Bump `products/custom/builder/VERSION` and publish with
      `./scripts/build-images.sh --builder`; verify the push succeeds and re-running the
      command refuses to overwrite the published version.
- [ ] 5.2 Repoint `builder_image` in `tf/app/variables.tf` at the new version and apply;
      verify `terraform validate` passes and the build Job's `image` names the new version
      once applied.
- [ ] 5.3 Deploy one project with a root Dockerfile and one without, end to end; verify the
      first builds from its Dockerfile and serves, the second is unchanged, and both build
      logs name the builder that ran.
