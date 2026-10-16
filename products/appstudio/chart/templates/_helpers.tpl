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

{{/*
Every header the platform's app authentication owns on the way to the app.
Mirrors identityHeaders in daemons/app-auth/request.go.
*/}}
{{- define "appstudio.identityHeaders" -}}
["X-Freepod-User","X-Freepod-Email","X-Freepod-Name","X-Freepod-Jwt","Remote-User","X-Forwarded-User","X-Forwarded-Email"]
{{- end -}}

{{/* The sign-in middlewares every route carries, strip first, then `extra`. */}}
{{- define "appstudio.routerMiddlewares" -}}
{{- $ns := .root.Release.Namespace -}}
{{- $name := .root.Release.Name -}}
{{- $mw := list (printf "%s-%s-strip-identity@kubernetescrd" $ns $name) (printf "%s-%s-app-auth@kubernetescrd" $ns $name) -}}
{{- range .extra -}}
{{- $mw = append $mw (printf "%s-%s-%s@kubernetescrd" $ns $name .) -}}
{{- end -}}
{{- join "," $mw -}}
{{- end -}}

{{/* projectDir as a path inside the workspace volume. */}}
{{- define "appstudio.projectSubPath" -}}
{{- $sub := trimPrefix "/workspace/" .Values.projectDir -}}
{{- if or (eq $sub .Values.projectDir) (eq $sub "") (contains ".." $sub) -}}
{{- fail (printf "appstudio: projectDir %q must be a directory inside /workspace" .Values.projectDir) -}}
{{- end -}}
{{- trimSuffix "/" $sub -}}
{{- end -}}

{{/* Pod template only; see "custom.podLabels" in the custom chart. */}}
{{- define "appstudio.podLabels" -}}
{{- with .Values.caelus.releaseId -}}
caelus.dev/release-id: {{ . | quote }}
{{- end -}}
{{- end -}}
