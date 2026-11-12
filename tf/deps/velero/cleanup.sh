#!/bin/bash
# Removes the Kopia repository of every namespace that no longer exists and
# that no remaining backup references (volume-backups spec). Any failed lookup
# aborts the run, so an API error never reads as "gone".
set -euo pipefail

export AWS_CONFIG_FILE=/tmp/aws-config
printf '[default]\ns3 =\n    addressing_style = path\n' >"$AWS_CONFIG_FILE"

referenced=$(kubectl -n "$VELERO_NAMESPACE" get datauploads \
  -o jsonpath='{range .items[*]}{.spec.sourceNamespace}{"\n"}{end}')
repos=$(kubectl -n "$VELERO_NAMESPACE" get backuprepositories \
  -o jsonpath='{range .items[*]}{.metadata.name} {.spec.volumeNamespace}{"\n"}{end}')

while read -r repo ns; do
  [[ -n $repo && -n $ns ]] || continue
  found=$(kubectl get namespace "$ns" --ignore-not-found -o name)
  [[ -z $found ]] || continue
  ! grep -qxF "$ns" <<<"$referenced" || continue

  echo "removing $repo"
  aws s3 rm --recursive --only-show-errors --endpoint-url "$S3_URL" "s3://$BUCKET/kopia/$ns/"
  kubectl -n "$VELERO_NAMESPACE" delete jobs -l "velero.io/repo-name=$repo" --ignore-not-found
  kubectl -n "$VELERO_NAMESPACE" delete backuprepository "$repo" --ignore-not-found
done <<<"$repos"
echo "done"
