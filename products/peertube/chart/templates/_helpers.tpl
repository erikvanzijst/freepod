{{- define "peertube.labels" -}}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: peertube
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{- define "peertube.componentSelector" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}

{{- define "peertube.image" -}}
{{- /* A digest-pinned tag is written tag@sha256:..., which is the reference itself. */ -}}
{{- printf "%s:%s" .Values.image.repository (.Values.image.tag | default .Chart.AppVersion | toString) -}}
{{- end -}}

{{/*
A generated credential, stable across upgrades: the value already in the named
Secret wins, then an explicit value, then a fresh one. The database password
seeds the data directory and PEERTUBE_SECRET signs sessions and federation
keys, so neither may change once used.
lookup is empty under `helm template`, so a dry run renders a throwaway value.
*/}}
{{- define "peertube.stableSecret" -}}
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

{{- define "peertube.podLabels" -}}
{{- with .Values.caelus.releaseId -}}
caelus.dev/release-id: {{ . | quote }}
{{- end -}}
{{- end -}}

{{/*
Pod-level placement shared by every pod in the release. Root in any container
maps to an unprivileged host uid. The node pool is preferred, not required,
so a release still schedules while the pool has no node.
*/}}
{{- define "peertube.podPlacement" -}}
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

{{/*
The environment every PeerTube process shares. Environment variables override
what the admin UI saves (node-config reads them last).
*/}}
{{- define "peertube.env" -}}
- name: PEERTUBE_WEBSERVER_HOSTNAME
  value: {{ .Values.host | quote }}
- name: PEERTUBE_DB_HOSTNAME
  value: {{ printf "%s-postgres" .Release.Name | quote }}
- name: PEERTUBE_DB_NAME
  value: {{ .Values.postgres.auth.database | quote }}
- name: PEERTUBE_DB_USERNAME
  value: {{ .Values.postgres.auth.username | quote }}
- name: PEERTUBE_REDIS_HOSTNAME
  value: {{ printf "%s-redis" .Release.Name | quote }}
- name: PEERTUBE_ADMIN_EMAIL
  value: {{ .Values.caelus.owner.email | default .Values.admin.email | quote }}
{{- if .Values.smtp.host }}
- name: PEERTUBE_SMTP_HOSTNAME
  value: {{ .Values.smtp.host | quote }}
- name: PEERTUBE_SMTP_PORT
  value: {{ .Values.smtp.port | quote }}
- name: PEERTUBE_SMTP_FROM
  value: {{ .Values.smtp.from | quote }}
- name: PEERTUBE_SMTP_TLS
  value: "false"
- name: PEERTUBE_SMTP_DISABLE_STARTTLS
  value: "true"
{{- end }}
# Live streaming ingests over RTMP, which has no route to the pod.
- name: PEERTUBE_LIVE_ENABLED
  value: "false"
- name: PEERTUBE_LIVE_RTMP_ENABLED
  value: "false"
- name: PEERTUBE_TRANSCODING_THREADS
  value: {{ .Values.transcoding.threads | quote }}
- name: PEERTUBE_TRANSCODING_CONCURRENCY
  value: {{ .Values.transcoding.concurrency | quote }}
{{- range $key, $value := .Values.extraEnv }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
{{- end -}}
