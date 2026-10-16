{{- define "appstudio.labels" -}}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: appstudio
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{/* Stable: used in the StatefulSet's immutable selector and the Service. */}}
{{- define "appstudio.selectorLabels" -}}
app.kubernetes.io/name: appstudio
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* preview-<first label>.<rest>, or empty when there is no preview. */}}
{{- define "appstudio.previewHost" -}}
{{- $ingress := .Values.caelus.ingress -}}
{{- if and .Values.preview.enabled $ingress.enabled $ingress.tls.wildcard $ingress.host -}}
{{- $parts := splitn "." 2 $ingress.host -}}
{{- printf "preview-%s.%s" $parts._0 $parts._1 -}}
{{- end -}}
{{- end -}}

{{/* Pod template only; see "custom.podLabels" in the custom chart. */}}
{{- define "appstudio.podLabels" -}}
{{- with .Values.caelus.releaseId -}}
caelus.dev/release-id: {{ . | quote }}
{{- end -}}
{{- end -}}
