{{- define "docmost.labels" -}}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: docmost
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{- define "docmost.componentSelector" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}

{{- define "docmost.appTag" -}}
{{- .Values.image.tag | default .Chart.AppVersion | toString -}}
{{- end -}}

{{/*
A generated credential, stable across upgrades: the value already in the named
Secret wins, then an explicit value, then a fresh one. The database password
seeds the data directory and APP_SECRET signs every session, so neither may
change once used.
lookup is empty under `helm template`, so a dry run renders a throwaway value.
*/}}
{{- define "docmost.stableSecret" -}}
{{- $existing := lookup "v1" "Secret" .root.Release.Namespace (printf "%s-%s" .root.Release.Name .secret) -}}
{{- $data := dict -}}
{{- if $existing }}{{- $data = $existing.data -}}{{- end -}}
{{- if hasKey $data .key -}}
{{- index $data .key | b64dec -}}
{{- else if .value -}}
{{- .value -}}
{{- else -}}
{{- randAlphaNum (.length | default 24) -}}
{{- end -}}
{{- end -}}

{{- define "docmost.podLabels" -}}
{{- with .Values.caelus.releaseId -}}
caelus.dev/release-id: {{ . | quote }}
{{- end -}}
{{- end -}}
