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
