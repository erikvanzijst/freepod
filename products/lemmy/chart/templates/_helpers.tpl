{{/* Common labels for every object this chart owns. */}}
{{- define "lemmy.labels" -}}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: lemmy
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{/* Stable selector labels for a named component (lemmy / lemmy-ui / pictrs / proxy / postgresql). */}}
{{- define "lemmy.componentSelector" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}

{{/* Resolved backend image tag: explicit image.tag wins, otherwise appVersion. */}}
{{- define "lemmy.imageTag" -}}
{{- .Values.image.tag | default .Chart.AppVersion -}}
{{- end -}}

{{/*
Resolved frontend image tag. Falls back to the backend's resolved tag: lemmy-ui
speaks a versioned API and is only supported against its matching backend
release, so the two must never float apart. The catalog pins `image.tag` alone.
*/}}
{{- define "lemmy.uiImageTag" -}}
{{- .Values.ui.image.tag | default (include "lemmy.imageTag" .) -}}
{{- end -}}

{{/*
A generated-once, then stable secret value.
  1. reuse the value already in the <release>-secrets Secret if present, so a
     helm upgrade never rotates a live credential;
  2. else honour an explicit value from values.yaml;
  3. else generate a fresh randAlphaNum.

lookup returns empty under `helm template`/`--dry-run`, so a dry-run with no
explicit value renders a throwaway; the reconciler always performs real installs,
so in practice each value generates once and is then reused. The hasKey guard
keeps `b64dec nil` from hard-failing if the Secret ever lacks the key.

Every caller must live in templates/secrets.yaml. Helm gives each *file* its own
variable scope, so deriving a value in two files would call randAlphaNum twice
and produce two different secrets on first install -- the config.hjson password
would not match the one Postgres was initialised with.

Args: root, key, value (explicit override, may be empty), length (default 24).
*/}}
{{- define "lemmy.stableSecret" -}}
{{- $existing := lookup "v1" "Secret" .root.Release.Namespace (printf "%s-secrets" .root.Release.Name) -}}
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

{{/*
Database host: an explicit postgresql.host wins, otherwise the bundled
StatefulSet's headless Service. Setting postgresql.enabled=false without a host
would otherwise render a config pointing at a Service the release never creates.
*/}}
{{- define "lemmy.postgresHost" -}}
{{- .Values.postgresql.host | default (printf "%s-postgresql" .Release.Name) -}}
{{- end -}}

{{/*
Object-level labels for a component's workload: the common set plus the
component name. Distinct from lemmy.componentSelector, which also carries
app.kubernetes.io/instance -- emitting both into one metadata.labels map would
set that key twice. Kubernetes' YAML parser tolerates the duplicate (last wins,
same value), but it is invalid YAML and strict validators reject the manifest.
*/}}
{{- define "lemmy.componentLabels" -}}
{{ include "lemmy.labels" .root }}
app.kubernetes.io/name: {{ .name }}
{{- end -}}
