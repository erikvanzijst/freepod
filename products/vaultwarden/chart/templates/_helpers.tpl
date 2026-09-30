{{/* Common labels for every object this chart owns. */}}
{{- define "vaultwarden.labels" -}}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: vaultwarden
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{/* Stable selector labels for the app pod. */}}
{{- define "vaultwarden.selectorLabels" -}}
app.kubernetes.io/name: vaultwarden
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Canonical public URL, rendered into the DOMAIN env. Vaultwarden needs it for the
admin console, email invitation links, and WebAuthn 2FA.

Prefers the reconciler-injected caelus.ingress.host (already lowercased, and the
host the Ingress actually routes) over the raw user value, so DOMAIN always
matches the hostname the browser used. Because this lands inline in the pod spec,
a hostname change alters the pod template and Helm rolls the pod automatically.
*/}}
{{- define "vaultwarden.domain" -}}
{{- $host := required "vaultwarden: caelus.ingress.host or host is required to derive DOMAIN" (coalesce .Values.caelus.ingress.host .Values.host) -}}
{{- printf "https://%s" $host -}}
{{- end -}}

{{/*
Admin console token. The console is a platform-operated surface, not a tenant
one: it exists so the bootstrap Job can invite the owner, and it is deliberately
never surfaced to the user. Its config editor writes /data/config.json, which
overrides the environment and would detach the instance from this chart.

Generated once and then stable:
  1. an explicit admin.token from system values wins, so an operator can pin one;
  2. else reuse the value already in the Secret, so an upgrade never rotates a
     live token out from under the running pod;
  3. else generate one.
lookup returns empty under `helm template`/`--dry-run`, so a dry run renders a
throwaway value; the reconciler always performs real installs, so in practice the
token generates once and is then reused.
*/}}
{{- define "vaultwarden.adminToken" -}}
{{- if .Values.admin.token -}}
{{- .Values.admin.token -}}
{{- else -}}
{{- $existing := lookup "v1" "Secret" .Release.Namespace (printf "%s-admin" .Release.Name) -}}
{{- $data := dict -}}
{{- if $existing }}{{- $data = $existing.data -}}{{- end -}}
{{- if hasKey $data "admin-token" -}}
{{- index $data "admin-token" | b64dec -}}
{{- else -}}
{{- randAlphaNum 20 -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "vaultwarden.podLabels" -}}
{{- with .Values.caelus.releaseId -}}
caelus.dev/release-id: {{ . | quote }}
{{- end -}}
{{- end -}}
