{{/*
Common labels applied to every object this chart owns. Kept deliberately small;
per-component identity lives in the app.kubernetes.io/name of each workload.
*/}}
{{- define "photoprism.labels" -}}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: photoprism
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{/*
Selector labels for a named component (photoprism / mariadb). Used for both the
Deployment selector and its Service.
*/}}
{{- define "photoprism.componentSelector" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}

{{/*
Resolved image tag: explicit image.tag wins, otherwise the chart appVersion.
`toString` because upstream versions are six-digit dates -- an unquoted tag in
a values file arrives here as an integer.
*/}}
{{- define "photoprism.appTag" -}}
{{- .Values.image.tag | default .Chart.AppVersion | toString -}}
{{- end -}}

{{/*
A bundled-database credential: generated once, then stable across upgrades.
  1. reuse the value already in the <release>-db Secret if present, so a helm
     upgrade never rotates a credential the data directory was seeded with;
  2. else honour an explicit value from values;
  3. else generate a fresh randAlphaNum.
lookup returns empty under `helm template`/`--dry-run`, so a dry run renders a
throwaway value; the reconciler always performs real installs.
*/}}
{{- define "photoprism.dbSecretValue" -}}
{{- $existing := lookup "v1" "Secret" .root.Release.Namespace (printf "%s-db" .root.Release.Name) -}}
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

{{/*
The first-start admin password, held in its own Secret for the same reason:
PhotoPrism applies it when the account is created and ignores it afterwards, so
a value that changed between releases would be a password nobody holds.
*/}}
{{- define "photoprism.adminPassword" -}}
{{- $existing := lookup "v1" "Secret" .Release.Namespace (printf "%s-admin" .Release.Name) -}}
{{- $data := dict -}}
{{- if $existing }}{{- $data = $existing.data -}}{{- end -}}
{{- if hasKey $data "PHOTOPRISM_ADMIN_PASSWORD" -}}
{{- index $data "PHOTOPRISM_ADMIN_PASSWORD" | b64dec -}}
{{- else if .Values.admin.password -}}
{{- .Values.admin.password -}}
{{- else -}}
{{- randAlphaNum 20 -}}
{{- end -}}
{{- end -}}
