{{- define "discourse.labels" -}}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: discourse
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{- define "discourse.componentSelector" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}

{{- define "discourse.appTag" -}}
{{- .Values.image.tag | default .Chart.AppVersion | toString -}}
{{- end -}}

{{- define "discourse.image" -}}
{{- $tag := include "discourse.appTag" . -}}
{{- /* A digest-pinned tag is written tag@sha256:..., which is the reference itself. */ -}}
{{- printf "%s:%s" .Values.image.repository $tag -}}
{{- end -}}

{{/*
A generated credential, stable across upgrades: the value already in the named
Secret wins, then an explicit value, then a fresh one. The database password
seeds the data directory and the secret key base signs every session, so
neither may change once used.
lookup is empty under `helm template`, so a dry run renders a throwaway value.
*/}}
{{- define "discourse.stableSecret" -}}
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

{{- define "discourse.podLabels" -}}
{{- with .Values.caelus.releaseId -}}
caelus.dev/release-id: {{ . | quote }}
{{- end -}}
{{- end -}}

{{/*
Pod-level placement shared by every pod in the release. Root in any container
maps to an unprivileged host uid. The node pool is preferred, not required,
so a release still schedules while the pool has no node; local-path volumes
are created wherever their pod first lands and pin it there afterwards.
*/}}
{{- define "discourse.podPlacement" -}}
hostUsers: false
{{- with .Values.nodePool }}
tolerations:
  - key: caelus.dev/node-pool
    operator: Equal
    value: {{ . | quote }}
    effect: NoSchedule
affinity:
  nodeAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        preference:
          matchExpressions:
            - key: caelus.dev/node-pool
              operator: In
              values:
                - {{ . | quote }}
{{- end }}
{{- end -}}

{{- define "discourse.securityContext" -}}
runAsNonRoot: true
runAsUser: 1000
runAsGroup: 1000
allowPrivilegeEscalation: false
capabilities:
  drop: [ALL]
{{- end -}}

{{/*
The environment every Discourse process shares. A DISCOURSE_<NAME> variable
is either a global setting or, when <name> is a site setting, pins that site
setting and hides it from the admin UI.
*/}}
{{- define "discourse.env" -}}
- name: DISCOURSE_HOSTNAME
  value: {{ .Values.host | quote }}
- name: DISCOURSE_DB_HOST
  value: {{ printf "%s-postgres" .Release.Name | quote }}
- name: DISCOURSE_DB_USERNAME
  value: {{ .Values.postgres.auth.username | quote }}
- name: DISCOURSE_DB_NAME
  value: {{ .Values.postgres.auth.database | quote }}
- name: DISCOURSE_REDIS_HOST
  value: {{ printf "%s-redis" .Release.Name | quote }}
- name: HOME
  value: /home/discourse
- name: LD_PRELOAD
  value: /usr/lib/libjemalloc.so
- name: RAILS_LOG_TO_STDOUT
  value: "1"
# TLS ends at the ingress; every URL Discourse writes is https.
- name: DISCOURSE_FORCE_HTTPS
  value: "true"
{{- if .Values.smtp.host }}
- name: DISCOURSE_SMTP_ADDRESS
  value: {{ .Values.smtp.host | quote }}
- name: DISCOURSE_SMTP_PORT
  value: {{ .Values.smtp.port | quote }}
- name: DISCOURSE_SMTP_ENABLE_START_TLS
  value: "false"
- name: DISCOURSE_NOTIFICATION_EMAIL
  value: {{ .Values.smtp.from | quote }}
{{- end }}
{{- range $key, $value := .Values.extraEnv }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
{{- end -}}
