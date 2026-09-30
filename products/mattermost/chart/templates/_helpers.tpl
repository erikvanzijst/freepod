{{/*
Truncated fullname for the Mattermost deployment and its resources.
Kubernetes automatically appends a hash suffix to labels on Deployments
and StatefulSets (e.g. controller-revision-hash). Label values must be
≤ 63 characters, so the resource name must leave room for the suffix
(~11 chars). We cap at 52 characters.
*/}}
{{- define "mattermost.fullname" -}}
{{- printf "%s-mattermost" .Release.Name | trunc 52 | trimSuffix "-" -}}
{{- end -}}

{{- define "mattermost.postgresql.fullname" -}}
{{- printf "%s-postgresql" .Release.Name | trunc 52 | trimSuffix "-" -}}
{{- end -}}

{{- define "mattermost.podLabels" -}}
{{- with .Values.caelus.releaseId -}}
caelus.dev/release-id: {{ . | quote }}
{{- end -}}
{{- end -}}
