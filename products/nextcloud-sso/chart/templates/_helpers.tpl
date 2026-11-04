{{/* Common labels for every object this chart owns. */}}
{{- define "nextcloud.labels" -}}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: nextcloud
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{/* Stable selector labels for a named component (nextcloud / postgresql). */}}
{{- define "nextcloud.componentSelector" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}

{{/*
Resolved Nextcloud image tag: explicit image.tag wins, otherwise
"<appVersion>-apache" (the flavor this chart deploys).
*/}}
{{- define "nextcloud.imageTag" -}}
{{- .Values.image.tag | default (printf "%s-apache" .Chart.AppVersion) -}}
{{- end -}}

{{/*
A chart-generated credential, stable across upgrades:
  1. reuse the value already in the <release>-<secret> Secret if present, so a
     helm upgrade never rotates a live credential;
  2. else honor an explicit value from values;
  3. else generate a fresh randAlphaNum.
lookup returns empty under `helm template`/`--dry-run`, so a dry-run with no
explicit value renders a throwaway one; the reconciler always performs real
installs, so in practice the value generates once and is then reused. The
hasKey guard keeps `b64dec nil` from hard-failing if the Secret ever lacks the key.
*/}}
{{- define "nextcloud.stableSecret" -}}
{{- $existing := lookup "v1" "Secret" .root.Release.Namespace (printf "%s-%s" .root.Release.Name .secret) -}}
{{- $data := dict -}}
{{- if $existing }}{{- $data = $existing.data -}}{{- end -}}
{{- if hasKey $data .key -}}
{{- index $data .key | b64dec -}}
{{- else if .value -}}
{{- .value -}}
{{- else -}}
{{- randAlphaNum 24 -}}
{{- end -}}
{{- end -}}

{{- define "nextcloud.podLabels" -}}
{{- with .Values.caelus.releaseId -}}
caelus.dev/release-id: {{ . | quote }}
{{- end -}}
{{- end -}}

{{/*
Non-empty when Sign in with Freepod is on: `auth.enabled` with
`auth.protocol: oidc`, the only protocol this chart speaks.
*/}}
{{- define "nextcloud.sso" -}}
{{- if and .Values.auth.enabled (eq (.Values.auth.protocol | default "header") "oidc") -}}true{{- end -}}
{{- end -}}

{{/*
Fails the render when SSO is on without what it needs: the access list, since
Nextcloud creates an account for whoever the provider admits; the reconciler's
OIDC client; and the owner, provisioned by subject as an administrator.
*/}}
{{/*
Fails an upgrade that switches sign-in. With SSO, accounts are named after
Freepod subjects and have no passwords; without it, they are Nextcloud's own.
Neither set can sign in under the other. A release's mode is whether it holds
the freepod app's ConfigMap, which only SSO renders, so a release from before
this check or from the catalog chart counts as what it is. lookup is empty
under `helm template`, where the check does nothing.
*/}}
{{- define "nextcloud.modeUnchanged" -}}
{{- $ns := .Release.Namespace -}}
{{- if lookup "v1" "ConfigMap" $ns (printf "%s-config" .Release.Name) -}}
{{- $wasSso := not (empty (lookup "v1" "ConfigMap" $ns (printf "%s-freepod-app" .Release.Name))) -}}
{{- $isSso := not (empty (include "nextcloud.sso" .)) -}}
{{- if and $wasSso (not $isSso) -}}
{{- fail "nextcloud-sso: this Nextcloud was installed with Sign in with Freepod, which cannot be turned off: its accounts have no passwords" -}}
{{- else if and $isSso (not $wasSso) -}}
{{- fail "nextcloud-sso: this Nextcloud was installed with its own accounts, so Sign in with Freepod cannot be turned on: they could not sign in with it" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "nextcloud.ssoRequired" -}}
{{- if include "nextcloud.sso" . -}}
{{- if ne (.Values.auth.access | default "anyone") "listed" -}}
{{- fail "nextcloud-sso: auth.protocol oidc needs auth.access listed, because Nextcloud creates an account for whoever the provider admits" -}}
{{- end -}}
{{- $oidc := .Values.caelus.oidc | default dict -}}
{{- $owner := .Values.caelus.owner | default dict -}}
{{- $_ := required "nextcloud-sso: auth.enabled with auth.protocol oidc needs caelus.oidc.issuer, which the Caelus reconciler injects" $oidc.issuer -}}
{{- $_ = required "nextcloud-sso: auth.enabled with auth.protocol oidc needs caelus.oidc.clientId, which the Caelus reconciler injects" $oidc.clientId -}}
{{- $_ = required "nextcloud-sso: auth.enabled with auth.protocol oidc needs caelus.oidc.secretName, which the Caelus reconciler injects" $oidc.secretName -}}
{{- $_ = required "nextcloud-sso: auth.enabled with auth.protocol oidc needs caelus.owner.subject, the owner's Freepod account, provisioned as Nextcloud's first admin" $owner.subject -}}
{{- $_ = required "nextcloud-sso: auth.enabled with auth.protocol oidc needs caelus.owner.email, the owner who becomes Nextcloud's first admin" $owner.email -}}
{{- end -}}
{{- end -}}
