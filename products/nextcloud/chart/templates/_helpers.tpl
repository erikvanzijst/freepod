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
Bundled-Postgres password: generated once, then stable across upgrades.
  1. reuse the value already in the <release>-db Secret if present, so a helm
     upgrade never rotates a live DB credential;
  2. else honour an explicit postgresql.auth.password from values;
  3. else generate a fresh randAlphaNum.
lookup returns empty under `helm template`/`--dry-run`, so a dry-run with no
explicit password renders a throwaway value; the reconciler always performs real
installs, so in practice the password generates once and is then reused. The
hasKey guard keeps `b64dec nil` from hard-failing if the Secret ever lacks the key.
*/}}
{{- define "nextcloud.postgresPassword" -}}
{{- $existing := lookup "v1" "Secret" .Release.Namespace (printf "%s-db" .Release.Name) -}}
{{- $data := dict -}}
{{- if $existing }}{{- $data = $existing.data -}}{{- end -}}
{{- if hasKey $data "POSTGRES_PASSWORD" -}}
{{- index $data "POSTGRES_PASSWORD" | b64dec -}}
{{- else if .Values.postgresql.auth.password -}}
{{- .Values.postgresql.auth.password -}}
{{- else -}}
{{- randAlphaNum 24 -}}
{{- end -}}
{{- end -}}

{{- define "nextcloud.podLabels" -}}
{{- with .Values.caelus.releaseId -}}
caelus.dev/release-id: {{ . | quote }}
{{- end -}}
{{- end -}}
