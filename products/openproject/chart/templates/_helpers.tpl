{{- define "openproject.labels" -}}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: openproject
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{- define "openproject.componentSelector" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}

{{- define "openproject.appTag" -}}
{{- .Values.image.tag | default (printf "%s-slim" .Chart.AppVersion) | toString -}}
{{- end -}}

{{/*
hocuspocus is released with OpenProject under the same version, so it follows
the application tag unless pinned on its own.
*/}}
{{- define "openproject.hocuspocusTag" -}}
{{- .Values.hocuspocus.image.tag | default (include "openproject.appTag" . | trimSuffix "-slim") | toString -}}
{{- end -}}

{{/*
A generated credential, stable across upgrades: the value already in the named
Secret wins, then an explicit value, then a fresh one. The database password
seeds the data directory, SECRET_KEY_BASE signs every session and encrypts
stored tokens, and the hocuspocus secret is shared by two processes, so none
may change once used.
lookup is empty under `helm template`, so a dry run renders a throwaway value.
*/}}
{{- define "openproject.stableSecret" -}}
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

{{- define "openproject.podLabels" -}}
{{- with .Values.caelus.releaseId -}}
caelus.dev/release-id: {{ . | quote }}
{{- end -}}
{{- end -}}

{{- define "openproject.securityContext" -}}
runAsNonRoot: true
runAsUser: 1000
runAsGroup: 1000
allowPrivilegeEscalation: false
capabilities:
  drop: [ALL]
{{- end -}}

{{/*
The configuration every OpenProject process shares: web, worker and seeder.
Settings given here are read-only in OpenProject's administration, so these
are the ones a tenant cannot move: the address, the cache, collaboration and
mail delivery. `env` overrides every envFrom source, so no var displaces them.
*/}}
{{- define "openproject.env" -}}
- name: OPENPROJECT_HOST__NAME
  value: {{ .Values.host | quote }}
# hocuspocus calls back over the Service, under its name rather than the host.
- name: OPENPROJECT_ADDITIONAL__HOST__NAMES
  value: {{ printf "%s-openproject" .Release.Name | quote }}
- name: OPENPROJECT_HTTPS
  value: "true"
- name: OPENPROJECT_HSTS
  value: "true"
- name: OPENPROJECT_RAILS__CACHE__STORE
  value: memcache
- name: OPENPROJECT_CACHE__MEMCACHE__SERVER
  value: {{ printf "%s-memcached:11211" .Release.Name | quote }}
- name: OPENPROJECT_COLLABORATIVE__EDITING__HOCUSPOCUS__URL
  value: {{ printf "wss://%s/hocuspocus" .Values.host | quote }}
# Versions are the platform's to upgrade, so the "update available" badge
# would point the tenant at something they cannot do.
- name: OPENPROJECT_SECURITY__BADGE__DISPLAYED
  value: "false"
- name: OPENPROJECT_WEB_MIN__THREADS
  value: {{ .Values.web.minThreads | quote }}
- name: OPENPROJECT_WEB_MAX__THREADS
  value: {{ .Values.web.maxThreads | quote }}
- name: OPENPROJECT_WEB_WORKERS
  value: {{ .Values.web.workers | quote }}
{{- if .Values.smtp.host }}
- name: OPENPROJECT_EMAIL__DELIVERY__METHOD
  value: smtp
- name: OPENPROJECT_SMTP__ADDRESS
  value: {{ .Values.smtp.host | quote }}
- name: OPENPROJECT_SMTP__PORT
  value: {{ .Values.smtp.port | quote }}
- name: OPENPROJECT_SMTP__AUTHENTICATION
  value: none
- name: OPENPROJECT_SMTP__ENABLE__STARTTLS__AUTO
  value: "false"
- name: OPENPROJECT_MAIL__FROM
  value: {{ .Values.smtp.from | quote }}
{{- end }}
{{- range $key, $value := .Values.extraEnv }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
{{- end -}}
