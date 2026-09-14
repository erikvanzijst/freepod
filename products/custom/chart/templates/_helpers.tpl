{{/* Common labels for every object this chart owns. */}}
{{- define "custom.labels" -}}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: custom
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{/* Stable selector labels for the app pod.

Stable is the operative word, and nothing per-release may be added here. This
helper is included in three places and two of them cannot tolerate a value that
changes between applies:

  deployment.yaml  spec.selector.matchLabels     IMMUTABLE -- a second apply
                                                 fails with "field is immutable"
  deployment.yaml  spec.template.metadata.labels the only mutable one
  service.yaml     spec.selector                 would select only the new
                                                 release's pods before they are
                                                 ready, dropping traffic
                                                 mid-rollout

Per-release labels belong in "custom.podLabels" below, which is used at the pod
template and nowhere else. */}}
{{- define "custom.selectorLabels" -}}
app.kubernetes.io/name: custom
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Per-release labels for the app pod, and for the pod template *only*.

`caelus.dev/release-id` identifies the individual rollout that produced a pod,
so that a log query can attribute a line to one release even while two rollouts'
pods are writing concurrently. Promtail relabels it into a `release_id` Loki
stream label (tf/deps/loki).

The value comes from the reconciler as a system override, so a tenant cannot
claim another release's id -- `merge_values_scoped` applies system values last,
which is the same thing `caelus.owner.id` above rests on.

Because the id exists before any pod does, every pod of the release carries it,
including one created hours later by an eviction or a kubelet restart with
nobody watching. Timestamps and pod names cannot do that: both are learned by
observation, and both mislabel a pod born after the observer stopped looking.

Emitted only when the value is present, so the chart still renders standalone
(`helm lint`, `helm template` with no --set).

Consequence, accepted: a fresh id changes the pod template hash on every apply,
so a redeploy with identical values genuinely cycles pods rather than being a
Helm no-op. That matches Heroku, Railway and Fly; at `replicas: 1` it costs a
brief interruption. */}}
{{- define "custom.podLabels" -}}
{{- with .Values.caelus.releaseId -}}
caelus.dev/release-id: {{ . | quote }}
{{- end -}}
{{- end -}}

{{/*
Resolve the container image to run, and — the point of this chart — prove that
the user asking for it is the user it was built for.

`.Values.image` is tenant-supplied in the form "{user_id}@{digest}", e.g.
"5@sha256:<64 hex>". That is exactly a real image reference with the registry
host stripped off: the repository is the owner's user id, so the pull reference
is composed here by prefixing `caelus.registry.prefix`, which the reconciler
injects per environment (registry-chart-contract).

Keeping the registry host out of the tenant's hands is half the guarantee; the
ownership check is the other half. It compares the "{user_id}" repository against
`caelus.owner.id`, which the reconciler injects from the deployment's owning
user. The comparison is sound only because `merge_values_scoped`
(api/app/services/template_values.py) applies system overrides *last*, so a
tenant cannot shadow caelus.owner.id with their own values. See
api/app/services/reconcile.py:_build_owner_overrides.

This lives in the chart on purpose. The alternative — special-casing image
references inside `update_deployment` — would leak build- and image-specific
knowledge into the generic deployment path that every other product shares.

Failures use `fail` with the mismatching values spelled out, because the message
surfaces to the end user as a deployment error; a raw Helm template error would
tell them nothing actionable.

With no image set the deployment is pre-build (`freepod init` claims the hostname
before anything is built) and the placeholder is served instead. The placeholder
is a system value, so it never reaches this assertion and never needs to.
*/}}
{{- define "custom.imageRef" -}}
{{- $image := trim (default "" .Values.image) -}}
{{- if not $image -}}
{{- required "custom: placeholderImage is required to render a deployment with no image" .Values.placeholderImage -}}
{{- else -}}
{{- $parts := splitList "@" $image -}}
{{- if ne (len $parts) 2 -}}
{{- fail (printf "custom: image %q is not of the form \"{user_id}@{digest}\" (for example \"5@sha256:\" followed by 64 hex characters)" $image) -}}
{{- end -}}
{{- $repository := index $parts 0 -}}
{{- $digest := index $parts 1 -}}
{{- if not (regexMatch "^[0-9]+$" $repository) -}}
{{- fail (printf "custom: image repository %q is not a numeric user id; expected \"{user_id}@{digest}\"" $repository) -}}
{{- end -}}
{{- if not (regexMatch "^sha256:[0-9a-f]{64}$" $digest) -}}
{{- fail (printf "custom: image digest %q is not a sha256 digest of 64 lowercase hex characters" $digest) -}}
{{- end -}}
{{- $owner := .Values.caelus.owner.id -}}
{{- if kindIs "invalid" $owner -}}
{{- fail "custom: caelus.owner.id is missing, so image ownership cannot be verified; the Caelus reconciler injects it for every deployment" -}}
{{- end -}}
{{- $ownerId := toString $owner -}}
{{- if ne $repository $ownerId -}}
{{- fail (printf "custom: image repository %q does not match deployment owner %q; an image can only be deployed by the user it was built for" $repository $ownerId) -}}
{{- end -}}
{{- /* Both halves are validated above, so prefixing the registry is all that is
       left — the tenant value is already a well-formed digest reference. */ -}}
{{- printf "%s/%s" (required "custom: caelus.registry.prefix is missing, so the image cannot be located; the Caelus reconciler injects it for every deployment" .Values.caelus.registry.prefix) $image -}}
{{- end -}}
{{- end -}}
