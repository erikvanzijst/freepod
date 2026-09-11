## 1. Keys and settings

- [ ] 1.1 Add `caelus registry-keygen` emitting an EC P-256 private key in PEM and the matching JWKS JSON with a `kid` — verify the printed JWKS parses and its key id matches the one the signing helper puts in a token header
- [ ] 1.2 Add the signing-key, HMAC-key, registry host and token-endpoint settings to `api/app/config.py`, absent by default so every non-registry path still constructs settings — verify `cd api && uv run --no-sync pytest` passes with none of them set
- [ ] 1.3 Generate one keypair and one HMAC key per environment, add them to `tf/app/secrets.auto.tfvars` keyed by workspace, and declare the variables — verify `terraform validate` passes in both workspaces

## 2. The registry (`tf/app`)

- [ ] 2.1 Add the registry namespace per environment (`caelus-registry` / `caelus-registry-dev`) — verify `terraform plan` creates exactly one per workspace and no other namespace changes
- [ ] 2.2 Add the registry Deployment (`registry:3`, one replica, `Recreate`), its PVC, and its config with `auth.token` (realm, issuer, service, jwks) and `delete: enabled` — verify the pod reaches Ready and `GET /v2/` returns 401 with a `Bearer realm=…` challenge naming the environment's token endpoint
- [ ] 2.3 Add the Service with a pinned `clusterIP`, confirming at apply time that the chosen address is unallocated — verify the address matches the plan after apply and survives a `kubectl rollout restart` of the Deployment
- [ ] 2.4 Add the JWKS ConfigMap and mount it — verify the registry accepts a token signed by the environment's key and rejects one signed by the other environment's key
- [ ] 2.5 Add the Certificate resource against `letsencrypt-dns` and serve TLS from it — verify `openssl s_client` against the ClusterIP from inside the cluster shows a valid chain for the registry's own name
- [ ] 2.6 Add the weekly restart CronJob and the Role and RoleBinding letting it restart only that Deployment — verify a manual `kubectl create job --from=cronjob/…` restarts the registry and the job's ServiceAccount cannot restart anything else
- [ ] 2.7 Add the garbage collection CronJob — verify a manual run completes and reports reclaimed blobs against a repository with unreferenced content
- [ ] 2.8 Confirm the reachability the design assumes without adding a policy in the registry namespace (D18): verify that a tenant application pod cannot reach the registry, that a build pod can, and that the node can pull
- [ ] 2.9 Publish the DNS records for both names pointing at the pinned ClusterIPs — verify each resolves from the node and that a client outside the cluster cannot connect

## 3. Token endpoint

- [ ] 3.1 Add `GET`/`POST /api/registry/token` to the API, accepting both the form-encoded exchange and the header-carried one — verify a unit test covers both forms and that neither requires the caller to retry in the other
- [ ] 3.2 Implement credential verification by HMAC recomputation over `registry-pull:v1:{uid}` with username `pull-{uid}` — verify a test asserts a wrong password, an unknown user and a mismatched version marker all yield no token
- [ ] 3.3 Implement scope filtering: return the intersection of the requested scope and the credential's authority, pull-only, never write, never delete, never catalog — verify tests assert that a request for `push`, for `delete`, for another owner's repository, and for the catalog each return no such access
- [ ] 3.4 Sign the returned token with the environment's key, with `iss`, `aud`, `exp`, `nbf` and `kid` set as the registry expects — verify an integration test has the real registry accept a token minted by this endpoint

## 4. Build path

- [ ] 4.1 Add capability minting to `api/app/services/build_jobs.py`: six exact repository entries, expiry at the build deadline plus margin, signed with the build worker's key — verify a test asserts the exact access list, that no entry is a pattern, and that neither `delete` nor the catalog appears
- [ ] 4.2 Pass the capability to the Job and have `build.py` write it into the pod's Docker configuration as `registrytoken` — verify a real build pushes to the new registry
- [ ] 4.3 Remove `registry.insecure=true` from all three call sites in `build.py` and make `read_image_config` verify TLS and send the capability as a bearer token — verify a build's post-push inspection still reports the runtime-contract warnings
- [ ] 4.4 Drop `CAELUS_CACHE_SCOPE`: `cache_ref` derives from the owner alone, and the worker stops setting it — verify `cd api && uv run --no-sync pytest api/tests/test_builder_script.py` passes with the scope argument gone
- [ ] 4.5 Bump `products/custom/builder/VERSION`, publish, and point `builder_image` at it in Terraform — verify a build runs end to end on the published image and its layer cache is imported on a second run of the same project

## 5. Mirrors and image migration

- [ ] 5.1 Repoint `scripts/mirror-railpack-images.sh` at the new registries and drop its `--insecure` flag — verify both frontend digest checks pass against each environment's registry
- [ ] 5.2 Point the builder's mirror configuration at the new registry — verify a build's log shows the base images resolving through it rather than from ghcr.io
- [ ] 5.3 Copy the 17 referenced images into the new registries with digests preserved — verify each copied image reports the same digest it had on the old registry
- [ ] 5.4 Verify a tenant capability cannot reach the mirror repositories for writing: attempt a push to `railwayapp/railpack-builder` with a build capability and confirm the registry refuses it

## 6. Chart and reconciler

- [ ] 6.1 Add the registry host and pull-Secret name as reconciler-injected system values, following `_build_ssh_overrides` — verify a test asserts a tenant-supplied value cannot shadow either
- [ ] 6.2 Publish the pull Secret per deployment namespace before Helm runs, alongside the existing storage and database Secrets — verify the Secret is present with `type: kubernetes.io/dockerconfigjson` and its password recomputes from the HMAC key
- [ ] 6.3 Add `imagePullSecrets` and the system values to the `custom` chart and its schema — verify `helm template` renders the pull secret reference for a deployment with an image, and renders without one for a deployment still on the placeholder
- [ ] 6.4 Bump the `custom` chart version and publish it to ghcr.io — verify `helm show chart` resolves the new version anonymously
- [ ] 6.5 Update `products/catalog/custom.yaml` to the new chart version — verify `caelus catalog lint` passes and a rollout creates exactly one new template version

## 7. Deployment migration

- [ ] 7.1 Move one `custom` deployment per environment to the new template version — verify each reaches `ready`, serves traffic, and its pod pulled from the new registry
- [ ] 7.2 Move the remaining `custom` deployments — verify every one reaches `ready` and no pod references the old registry
- [ ] 7.3 Audit that no template and no live deployment in either environment resolves a tenant image from the old registry — verify the audit returns empty before continuing

## 8. Cutover

- [ ] 8.1 Remove the internal-registry entry from the node's `/etc/rancher/k3s/registries.yaml` — verify a tenant image still pulls after a kubelet restart, with no registry configuration on the node
- [ ] 8.2 Delete the tenant repositories, caches, mirrors and remaining platform repositories from the old registry — verify its catalog is empty of platform and tenant content and that one deployment per product still reconciles
- [ ] 8.3 Verify the end state against the threat that motivated the change: from a build pod, confirm that pulling another owner's image is refused, that pushing to another owner's repository is refused, that the catalog is refused, and that an unauthenticated request is refused

## 9. Documentation

- [ ] 9.1 Update `products/custom/builder/README.md`: the cache section without the environment scope, the mirror section against the new registry, and the node prerequisites reduced to the one that remains — verify no reference to the retired scope or the old registry survives
- [ ] 9.2 Update `api/README.md` § Builds, `tf/README.md` and `tf/app/README.md` for the registry, the token endpoint, the keys and `registry-keygen` — verify the two node prerequisites are described as one
- [ ] 9.3 Add the capability entry and links to `AGENTS.md` per its documentation-layering rule — verify it is a terse orientation plus links rather than a restatement of the specs
