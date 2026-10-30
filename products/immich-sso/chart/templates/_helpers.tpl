{{/*
Common labels applied to every object this chart owns. Kept deliberately small;
per-component identity lives in the app.kubernetes.io/name of each workload.
*/}}
{{- define "immich.labels" -}}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: immich
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{/*
Selector labels for a named component (server / machine-learning / valkey /
postgresql). Used for both the Deployment selector and its Service.

A Deployment's spec.selector is immutable: it can never be changed once the
object exists. The server/machine-learning/valkey Deployments are named
<release>-<component>, so an existing in-cluster Deployment of that name is
patched in place rather than recreated -- which means this selector must equal
whatever those Deployments were already created with, including the
app.kubernetes.io/controller: main label they carry. Dropping it would make
`helm upgrade` fail with "field is immutable".
*/}}
{{- define "immich.componentSelector" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/controller: main
{{- end -}}

{{/*
Resolved image tag for the immich app containers: explicit image.tag wins,
otherwise the chart appVersion. Centralised so server + machine-learning never
drift apart.
*/}}
{{- define "immich.appTag" -}}
{{- .Values.image.tag | default .Chart.AppVersion -}}
{{- end -}}

{{- define "immich.podLabels" -}}
{{- with .Values.caelus.releaseId -}}
caelus.dev/release-id: {{ . | quote }}
{{- end -}}
{{- end -}}

{{/*
Non-empty when Sign in with Freepod is on: `auth.enabled` with
`auth.protocol: oidc`, the only protocol Immich speaks.
*/}}
{{- define "immich.sso" -}}
{{- if and .Values.auth.enabled (eq (.Values.auth.protocol | default "header") "oidc") -}}true{{- end -}}
{{- end -}}

{{/*
Fails the render when SSO is on without what it needs: the reconciler's OIDC
client, the owner who becomes the first admin, and an access list, since Immich
registers whoever the provider admits.
*/}}
{{- define "immich.ssoRequired" -}}
{{- if include "immich.sso" . -}}
{{- if ne (.Values.auth.access | default "anyone") "listed" -}}
{{- fail "immich-sso: auth.protocol oidc needs auth.access listed, because Immich registers whoever the provider admits" -}}
{{- end -}}
{{- $oidc := .Values.caelus.oidc | default dict -}}
{{- $_ := required "immich-sso: auth.enabled with auth.protocol oidc needs caelus.oidc.issuer, which the Caelus reconciler injects" $oidc.issuer -}}
{{- $_ = required "immich-sso: auth.enabled with auth.protocol oidc needs caelus.oidc.clientId, which the Caelus reconciler injects" $oidc.clientId -}}
{{- $_ = required "immich-sso: auth.enabled with auth.protocol oidc needs caelus.oidc.secretName, which the Caelus reconciler injects" $oidc.secretName -}}
{{- $_ = required "immich-sso: auth.enabled with auth.protocol oidc needs caelus.owner.email, the owner who becomes Immich's first admin" (.Values.caelus.owner | default dict).email -}}
{{- end -}}
{{- end -}}
