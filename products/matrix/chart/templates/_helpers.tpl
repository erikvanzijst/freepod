{{- define "matrix.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "matrix.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "matrix.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "matrix.labels" -}}
helm.sh/chart: {{ include "matrix.chart" . }}
app.kubernetes.io/name: {{ include "matrix.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "matrix.selectorLabels" -}}
app.kubernetes.io/name: {{ include "matrix.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "matrix.registrationSecretName" -}}
{{- printf "%s-registration" (include "matrix.fullname" .) -}}
{{- end -}}

{{- define "matrix.elementWeb.fullname" -}}
{{- printf "%s-element-web" (include "matrix.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "matrix.elementWeb.selectorLabels" -}}
app.kubernetes.io/name: element-web
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "matrix.elementWeb.labels" -}}
helm.sh/chart: {{ include "matrix.chart" . }}
{{ include "matrix.elementWeb.selectorLabels" . }}
app.kubernetes.io/version: {{ .Values.elementWeb.image.tag | quote }}
app.kubernetes.io/part-of: {{ include "matrix.name" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
