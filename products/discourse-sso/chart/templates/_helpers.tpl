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

{{/*
Non-empty when Sign in with Freepod is on: `auth.enabled` with
`auth.protocol: oidc`, the only protocol Discourse speaks.
*/}}
{{- define "discourse.sso" -}}
{{- if and .Values.auth.enabled (eq (.Values.auth.protocol | default "header") "oidc") -}}true{{- end -}}
{{- end -}}

{{/*
Fails the render when SSO is on without what it needs: the reconciler's OIDC
client, and the owner who becomes the first admin.
*/}}
{{- define "discourse.ssoRequired" -}}
{{- if include "discourse.sso" . -}}
{{- $oidc := .Values.caelus.oidc | default dict -}}
{{- $_ := required "discourse-sso: auth.enabled with auth.protocol oidc needs caelus.oidc.issuer, which the Caelus reconciler injects" $oidc.issuer -}}
{{- $_ = required "discourse-sso: auth.enabled with auth.protocol oidc needs caelus.oidc.clientId, which the Caelus reconciler injects" $oidc.clientId -}}
{{- $_ = required "discourse-sso: auth.enabled with auth.protocol oidc needs caelus.oidc.secretName, which the Caelus reconciler injects" $oidc.secretName -}}
{{- $_ = required "discourse-sso: auth.enabled with auth.protocol oidc needs caelus.owner.email, the owner who becomes Discourse's first admin" (.Values.caelus.owner | default dict).email -}}
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
{{- if include "discourse.sso" . }}
{{- $oidc := .Values.caelus.oidc }}
# Sign in with Freepod. Each of these pins its site setting, so an admin cannot
# turn it off or change the provider. Passkey login does not honor
# enable_local_logins, so it goes separately, and DiscourseConnect would replace
# Sign in with Freepod altogether. With local logins off Discourse counts every
# 2FA method as off, so a forum restored from a backup that requires 2FA would
# send everyone to a setup page that no longer works; the last pin below exempts
# sign-ins through Freepod. Other login methods only add to it, so they stay with
# the tenant, as does who may join: allow_new_registrations, invite_only,
# must_approve_users.
- name: DISCOURSE_OPENID_CONNECT_ENABLED
  value: "true"
- name: DISCOURSE_OPENID_CONNECT_DISCOVERY_DOCUMENT
  value: {{ printf "%s/.well-known/openid-configuration" (trimSuffix "/" $oidc.issuer) | quote }}
- name: DISCOURSE_OPENID_CONNECT_CLIENT_ID
  value: {{ $oidc.clientId | quote }}
- name: DISCOURSE_OPENID_CONNECT_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ $oidc.secretName | quote }}
      key: OIDC_CLIENT_SECRET
- name: DISCOURSE_OPENID_CONNECT_AUTHORIZE_SCOPE
  value: "openid email profile"
- name: DISCOURSE_OPENID_CONNECT_USE_PKCE
  value: "true"
# Links an account to the Freepod account holding its email on first sign-in:
# how the seeded owner is recognized, and how a forum restored from a backup
# made elsewhere keeps its members.
- name: DISCOURSE_OPENID_CONNECT_MATCH_BY_EMAIL
  value: "true"
- name: DISCOURSE_OPENID_CONNECT_RP_INITIATED_LOGOUT
  value: "true"
- name: DISCOURSE_OPENID_CONNECT_RP_INITIATED_LOGOUT_INCLUDE_CLIENT_ID
  value: "true"
- name: DISCOURSE_OPENID_CONNECT_RP_INITIATED_LOGOUT_REDIRECT
  value: {{ printf "https://%s/" .Values.host | quote }}
- name: DISCOURSE_ENABLE_LOCAL_LOGINS
  value: "false"
- name: DISCOURSE_ENABLE_LOCAL_LOGINS_VIA_EMAIL
  value: "false"
- name: DISCOURSE_ENABLE_PASSKEYS
  value: "false"
- name: DISCOURSE_ENABLE_DISCOURSE_CONNECT
  value: "false"
- name: DISCOURSE_ENFORCE_SECOND_FACTOR_ON_EXTERNAL_AUTH
  value: "false"
- name: DISCOURSE_AUTH_OVERRIDES_EMAIL
  value: "true"
- name: DISCOURSE_EMAIL_EDITABLE
  value: "false"
{{- end }}
{{- range $key, $value := .Values.extraEnv }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
{{- end -}}
