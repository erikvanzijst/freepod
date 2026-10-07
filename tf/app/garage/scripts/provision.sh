#!/bin/sh
# Idempotent bucket, access-key, permission and lifecycle provisioning for the
# environment's Garage instance. The whole of the `garage-provision` Job.
#
# WHY THIS TALKS TO THE ADMIN API AND NOT THE `garage` CLI
# -------------------------------------------------------
# The obvious implementation — run `garage bucket create` in the Garage image —
# is not available:
#
#   * `dxflrs/garage` is a FROM-scratch image whose only file is `/garage`.
#     There is no shell and no coreutils, so a script cannot run in it.
#   * The `garage` CLI speaks the internal RPC protocol and needs
#     `<full-node-id>@host:port`. The node ID does not exist until the pod has
#     run, so a second pod cannot address it without discovering it first.
#
# The admin API has neither problem: it is plain HTTP on :3903, addressed by
# Service name. Design D2 anticipates this ("where the admin API is used rather
# than the CLI, use a scoped, expirable admin token").
#
# The lifecycle rules used to be a second Job step in an S3-client image,
# because setting them was an S3-API call (`PutBucketLifecycleConfiguration`)
# that needed the bucket's own access key. As of Garage v2.3.0
# `POST /v2/UpdateBucket` takes `lifecycleRules` directly, in the same
# S3-shaped JSON, so that step folded into this one: one container, one image,
# one credential, and no S3 client anywhere in provisioning.
#
# EVERY STEP READS BEFORE IT WRITES, so a re-run is a no-op and an existing
# access key is never rotated. Terraform re-runs this Job whenever the script or
# its inputs change, which also repairs hand-made drift.
set -eu

: "${GARAGE_ADMIN_URL:?}"
: "${GARAGE_ADMIN_TOKEN:?}"
: "${BUCKET_NAME:?}"
: "${KEY_NAME:?}"
: "${KEYS_SECRET_NAME:?}"
: "${NAMESPACE:?}"
: "${OBJECT_EXPIRY_DAYS:?}"
: "${HEALTH_TIMEOUT_SECONDS:?}"
: "${API_TOKEN_NAME:?}"
: "${API_TOKEN_SECRET_KEY:?}"

log() { echo "[provision] $*" >&2; }

# --------------------------------------------------------------------------
# 1. Wait for a committed cluster layout.
#
# A freshly installed Garage node holds NO cluster layout and rejects every S3
# and data operation until an operator assigns and commits one; `/health`
# returns 503 until then. Polling rather than failing immediately means an
# operator can run the one-time bootstrap in another terminal while
# `terraform apply` waits here, instead of having the apply fail and be re-run.
# --------------------------------------------------------------------------
waited=0
while [ "$(curl -s -o /dev/null -w '%{http_code}' "$GARAGE_ADMIN_URL/health" || echo 000)" != "200" ]; do
  if [ "$waited" -ge "$HEALTH_TIMEOUT_SECONDS" ]; then
    log "FATAL: Garage still reports unhealthy after ${HEALTH_TIMEOUT_SECONDS}s."
    log ""
    log "On a fresh install the overwhelmingly likely cause is that the cluster"
    log "layout has never been assigned and committed. Garage cannot serve any"
    log "request without one. See tf/app/README.md -> 'Garage object store' ->"
    log "'Cluster-layout bootstrap' for the two commands, then re-run"
    log "'terraform apply'."
    log ""
    log "Current health:"
    curl -s "$GARAGE_ADMIN_URL/health" >&2 || true
    echo >&2
    exit 1
  fi
  log "waiting for Garage to report healthy (${waited}s/${HEALTH_TIMEOUT_SECONDS}s)..."
  sleep 5
  waited=$((waited + 5))
done
log "Garage is healthy; cluster layout is committed."

# --------------------------------------------------------------------------
# 2a. Ensure the Caelus API's own long-lived admin token exists.
#
# The API provisions a bucket and an access key per deployment at reconcile
# time, so it needs an admin credential of its own. It is scoped to exactly
# those operations and NEVER EXPIRES.
#
# That makes it the opposite animal from the short-lived, self-revoking token
# minted in 2b for this script's own work. Two tokens, two lifetimes, one
# script — deliberately. Do not "harmonize" them: giving the API an expiring
# credential would break every deployment reconcile an hour later.
#
# ITS SECRET CANNOT BE READ BACK. An access key can (GetKeyInfo?showSecretKey),
# which is what makes every other step here re-runnable. CreateAdminToken
# returns `secretToken` exactly once and GetAdminTokenInfo has no field for it.
# So the Kubernetes Secret written in step 4 is the store of record, and this
# step consults it first:
#
#   Secret has the token, and it still exists in Garage -> reuse; change nothing
#   Secret does not have it                             -> any existing token of
#                                                          this name is
#                                                          unrecoverable: delete
#                                                          it and mint a new one
#
# A re-run is therefore still a no-op in the normal case. If the Secret is lost
# the token rotates, which is the only recovery available, and the operator
# re-pastes it into tf/app exactly as with any other credential here.
# --------------------------------------------------------------------------
TOKEN="$GARAGE_ADMIN_TOKEN"

api() { # api <METHOD> <PATH> [JSON_BODY]
  _method="$1"
  _path="$2"
  _body="${3:-}"
  if [ -n "$_body" ]; then
    _code=$(curl -sS -o /tmp/api.out -w '%{http_code}' -X "$_method" \
      -H "Authorization: Bearer $TOKEN" \
      -H 'Content-Type: application/json' \
      -d "$_body" "${GARAGE_ADMIN_URL}${_path}")
  else
    _code=$(curl -sS -o /tmp/api.out -w '%{http_code}' -X "$_method" \
      -H "Authorization: Bearer $TOKEN" "${GARAGE_ADMIN_URL}${_path}")
  fi
  if [ "$_code" -lt 200 ] || [ "$_code" -ge 300 ]; then
    log "admin API $_method $_path failed with HTTP $_code:"
    cat /tmp/api.out >&2
    echo >&2
    return 1
  fi
  cat /tmp/api.out
}

# Absent Secret, absent key, or a malformed value all collapse to "empty", which
# is the re-mint path. `|| true` because a missing Secret is the first-run case,
# not an error.
api_admin_token=$(kubectl get secret "$KEYS_SECRET_NAME" --namespace "$NAMESPACE" \
  -o "jsonpath={.data.${API_TOKEN_SECRET_KEY}}" 2>/dev/null | base64 -d 2>/dev/null || true)

existing_api_token_id=$(api GET /v2/ListAdminTokens |
  jq -r --arg n "$API_TOKEN_NAME" 'map(select(.name == $n)) | .[0].id // empty')

if [ -n "$api_admin_token" ] && [ -n "$existing_api_token_id" ]; then
  log "Caelus API admin token '${API_TOKEN_NAME}' already provisioned (${existing_api_token_id})"
else
  if [ -n "$existing_api_token_id" ]; then
    log "admin token '${API_TOKEN_NAME}' exists (${existing_api_token_id}) but its secret is not"
    log "recoverable and is not in ${NAMESPACE}/${KEYS_SECRET_NAME}; replacing it."
    api POST "/v2/DeleteAdminToken?id=${existing_api_token_id}" >/dev/null
  fi
  # The scope is exactly what deployment provisioning calls and nothing more.
  # `CreateAdminToken`/`UpdateAdminToken` are absent on purpose: Garage
  # documents either as trivially equivalent to a scope of `*`.
  api_token_response=$(api POST /v2/CreateAdminToken "$(
    cat <<EOF
{"name":"${API_TOKEN_NAME}",
 "neverExpires":true,
 "scope":["ListBuckets","CreateBucket","GetBucketInfo","UpdateBucket",
          "ListKeys","CreateKey","GetKeyInfo","DeleteKey","AllowBucketKey"]}
EOF
  )")
  api_admin_token=$(echo "$api_token_response" | jq -r '.secretToken')
  log "minted Caelus API admin token '${API_TOKEN_NAME}' ($(echo "$api_token_response" | jq -r '.id'))"
fi

# --------------------------------------------------------------------------
# 2b. Mint a scoped, expiring admin token and do the real work with that.
#
# Required by the garage-bucket-provisioning spec: the working credential is
# limited to the seven endpoints below and expires on its own. Honest caveat —
# this pod still holds the master token, because minting a scoped token is
# itself a master-token operation. What this buys is that the credential
# actually used for the provisioning calls cannot read cluster status, cannot
# touch the layout, and cannot mint further tokens (Garage rejects
# `CreateAdminToken`/`UpdateAdminToken` in a scope as trivial privilege
# escalation), and that it is revoked on exit and expires regardless.
# --------------------------------------------------------------------------
SCOPED_TOKEN_ID=""
revoke_scoped_token() {
  [ -n "$SCOPED_TOKEN_ID" ] || return 0
  TOKEN="$GARAGE_ADMIN_TOKEN"
  api POST "/v2/DeleteAdminToken?id=${SCOPED_TOKEN_ID}" >/dev/null 2>&1 ||
    log "WARNING: could not revoke scoped admin token ${SCOPED_TOKEN_ID}; it expires on its own."
  SCOPED_TOKEN_ID=""
}
trap revoke_scoped_token EXIT INT TERM

expires_at=$(date -u -d "@$(($(date +%s) + 3600))" +%Y-%m-%dT%H:%M:%SZ)
token_response=$(api POST /v2/CreateAdminToken "$(
  cat <<EOF
{"name":"caelus-provisioning-$(date +%s)",
 "expiration":"${expires_at}",
 "scope":["ListBuckets","CreateBucket","UpdateBucket","ListKeys","CreateKey","GetKeyInfo","AllowBucketKey"]}
EOF
)")
SCOPED_TOKEN_ID=$(echo "$token_response" | jq -r '.id')
TOKEN=$(echo "$token_response" | jq -r '.secretToken')
log "using scoped admin token ${SCOPED_TOKEN_ID}, expiring ${expires_at}"

# --------------------------------------------------------------------------
# 3. The platform's own bucket, access key, permission grant, lifecycle rules.
#
# One of each per instance: the instance is per environment, so the names need
# not say which. Both come from Terraform (provisioning.tf).
# --------------------------------------------------------------------------
set --

bucket="$BUCKET_NAME"
key_name="$KEY_NAME"

bucket_id=$(api GET /v2/ListBuckets |
  jq -r --arg b "$bucket" 'map(select(.globalAliases | index($b))) | .[0].id // empty')
if [ -z "$bucket_id" ]; then
  bucket_id=$(api POST /v2/CreateBucket "{\"globalAlias\":\"${bucket}\"}" | jq -r '.id')
  log "created bucket '${bucket}' (${bucket_id})"
else
  log "bucket '${bucket}' already exists (${bucket_id})"
fi

access_key_id=$(api GET /v2/ListKeys |
  jq -r --arg n "$key_name" 'map(select(.name == $n)) | .[0].id // empty')
if [ -z "$access_key_id" ]; then
  # Garage mints the key material; it cannot be pre-generated by Terraform
  # because `ImportKey` rejects keys Garage did not generate (the access key
  # ID carries a checksum). This is the only moment the secret is returned by
  # a create call, but GetKeyInfo?showSecretKey can read it back later, which
  # is what makes the re-run path below possible without rotating anything.
  key_response=$(api POST /v2/CreateKey "{\"name\":\"${key_name}\",\"neverExpires\":true}")
  access_key_id=$(echo "$key_response" | jq -r '.accessKeyId')
  secret_access_key=$(echo "$key_response" | jq -r '.secretAccessKey')
  log "created access key '${key_name}' (${access_key_id})"
else
  log "access key '${key_name}' already exists (${access_key_id}) - not rotating"
  secret_access_key=$(api GET "/v2/GetKeyInfo?id=${access_key_id}&showSecretKey=true" |
    jq -r '.secretAccessKey')
fi

# Read and write on this bucket only. `owner` is deliberately
# omitted: AllowBucketKey activates the flags set to true and leaves the rest
# untouched, so omitting it neither grants nor is needed. Nothing in
# provisioning uses this key — it is minted for the Caelus API alone.
api POST /v2/AllowBucketKey \
  "{\"bucketId\":\"${bucket_id}\",\"accessKeyId\":\"${access_key_id}\",\"permissions\":{\"read\":true,\"write\":true}}" \
  >/dev/null
log "granted read+write on '${bucket}' to '${key_name}'"

# Both of the lifecycle actions Garage implements are used, and they reclaim
# different things:
#
#   Expiration                       completed objects past their age
#   AbortIncompleteMultipartUpload   parts of uploads that never completed
#
# The second is not optional. Abandoned multipart parts consume disk while
# never appearing in a bucket listing — exactly the kind of invisible growth
# that produced this node's earlier disk-pressure incident.
#
# Declarative expiry is why this design needs no reaper CronJob and no
# cleanup code: reclamation is a property of the bucket, so it cannot be
# forgotten by a caller, skipped by a failed job, or lost in a refactor.
#
# Idempotent like every other step, for the same reason the S3 call this
# replaces was: UpdateBucket assigns `lifecycleRules` wholesale rather than
# appending, so re-running converges instead of accumulating rules. Every
# field of the request body is optional and an absent one is left untouched,
# so this leaves the bucket's quotas, CORS and website access alone.
api POST "/v2/UpdateBucket?id=${bucket_id}" "$(
  cat <<EOF
{"lifecycleRules":[
{"ID":"expire-objects",
 "Status":"Enabled",
 "Filter":{"Prefix":""},
 "Expiration":{"Days":${OBJECT_EXPIRY_DAYS}}},
{"ID":"abort-incomplete-multipart-uploads",
 "Status":"Enabled",
 "Filter":{"Prefix":""},
 "AbortIncompleteMultipartUpload":{"DaysAfterInitiation":${OBJECT_EXPIRY_DAYS}}}
]}
EOF
)" >/dev/null
log "applied lifecycle to '${bucket}' (expiry ${OBJECT_EXPIRY_DAYS}d)"

set -- "$@" \
  --from-literal="access_key_id=${access_key_id}" \
  --from-literal="secret_access_key=${secret_access_key}"

# The API's admin token rides in the same Secret as the S3 credentials: same
# store of record, same handoff to tf/app, and step 2a reads it back from here.
set -- "$@" --from-literal="${API_TOKEN_SECRET_KEY}=${api_admin_token}"

# --------------------------------------------------------------------------
# 4. Publish the credentials as a Secret in this namespace.
#
# Terraform reads this back through a `kubernetes_secret` data source and
# exposes it as outputs, which the operator pastes into the gitignored
# tf/app/secrets.auto.tfvars — the same handoff ritual as the Keycloak client
# secrets. The Job deliberately does NOT write into tf/app's namespaces: that
# would need cross-namespace write RBAC and would invert the ownership boundary
# between the two root modules.
# --------------------------------------------------------------------------
kubectl create secret generic "$KEYS_SECRET_NAME" \
  --namespace "$NAMESPACE" "$@" \
  --dry-run=client -o yaml | kubectl apply -f - >&2

log "wrote Secret ${NAMESPACE}/${KEYS_SECRET_NAME}"
log "done."
