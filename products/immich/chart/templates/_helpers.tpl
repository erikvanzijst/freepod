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
