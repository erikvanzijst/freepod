{{- /*
The SSH sidecar: the platform's own server, run by every product that offers
SSH access at all. There is one helper set, because there is one server.

A product declares exactly one thing — `sessionRoot` — and everything else
follows from it.

Call sites in a product chart:

  # the Service, from its own template file:
  {{ include "ssh-sidecar.resources" (dict "root" .) }}

  # the sidecar container, spliced into the pod's `containers:`:
  {{ include "ssh-sidecar.sidecar" (dict "root" . "image" .Values.sshSidecarImage
       "sessionRoot" "volume:/data"
       "mounts" (list (dict "volume" "data" "path" "/data"))) }}

An `app-container` session root additionally requires `shareProcessNamespace:
true` on the pod, which is a pod-level field no container helper can reach and
which the product chart therefore sets itself. Without it the container still
starts and serves; forwarding works, and a session that needs the application
container says what is missing.

**This chart renders no Secret and no ConfigMap.** Everything per-deployment
reaches the sidecar as an environment variable: the trusted key is a *public*
key, the session root is a string, and the database variables come from the
Secret the reconciler already writes. The image writes its own
`authorized_keys`, `sshd_config` and host key at startup, so an object of either
kind would be one nothing reads.
*/}}

{{- /*
ssh-sidecar.sessionJail — where the image roots a volume session, and therefore
where this chart must mount what the product exposes.
*/}}
{{- define "ssh-sidecar.sessionJail" -}}/srv/session{{- end -}}

{{- /*
ssh-sidecar.resources — the standalone objects, which are the Service and
nothing else.
*/}}
{{- define "ssh-sidecar.resources" -}}
{{ include "ssh-sidecar.service" (dict "root" .root "serviceName" .serviceName "selector" .selector) }}
{{- end -}}

{{- /*
ssh-sidecar.sidecar — the sidecar container. Splice into the pod's
`containers:` list.

Required params:
  image        the sidecar image.
  sessionRoot  `app-container`, or `volume:/<path>` naming where in the session
               the product's data appears.

Required with a volume session root, and refused without one:
  mounts       a list of {volume, path[, subPath]}. `volume` is an existing pod
               volume, `path` is where it appears in the session, and optional
               `subPath` exposes only a subdirectory of the volume -- use it
               when the volume also holds application config that must not be
               readable (nextcloud's config.php carries database credentials).
               Every mount is rendered read-only. NEVER list a database volume.

Every runtime input below is platform-projected, and none is `required` here on
purpose: the image validates all of them and exits naming the offending
variable, which is a pod that will not start rather than one that starts
misconfigured. `sessionRoot` is the exception, because it is the one input this
chart can check and the one whose absence must never resolve to a default.
*/}}
{{- define "ssh-sidecar.sidecar" -}}
{{- $root := .root -}}
{{- $caelus := $root.Values.caelus | default dict -}}
{{- $db := $caelus.database | default dict -}}
{{- $ssh := $caelus.ssh | default dict -}}
{{- $jail := include "ssh-sidecar.sessionJail" . -}}
{{- $sessionRoot := .sessionRoot | default "" -}}
{{- if not $sessionRoot -}}
{{- fail "ssh-sidecar.sidecar: `sessionRoot` is required. It is `app-container` or `volume:/<path>`; there is no default, and a product wanting no SSH access renders no sidecar at all rather than declaring a third value." -}}
{{- end -}}
{{- $isApp := eq $sessionRoot "app-container" -}}
{{- $isVolume := hasPrefix "volume:/" $sessionRoot -}}
{{- if not (or $isApp $isVolume) -}}
{{- fail (printf "ssh-sidecar.sidecar: `sessionRoot` is %q, which is not a session root. Use `app-container` or `volume:/<absolute path>`." $sessionRoot) -}}
{{- end -}}
{{- $sessionPath := trimPrefix "volume:" $sessionRoot -}}
{{- if and $isApp .mounts -}}
{{- fail "ssh-sidecar.sidecar: `mounts` was passed alongside `app-container`. An application-rooted session is rooted at the application container's own filesystem; a volume mounted here would be a second, unreachable copy." -}}
{{- end -}}
{{- if and $isVolume (not .mounts) -}}
{{- fail "ssh-sidecar.sidecar: a volume session root needs `mounts`. A sidecar with nothing mounted offers a session that can list nothing; a product with nothing to expose renders no sidecar at all." -}}
{{- end -}}
{{- if $isVolume -}}
{{- $paths := list -}}
{{- range .mounts }}{{ $paths = append $paths .path }}{{ end -}}
{{- if not (has $sessionPath $paths) -}}
{{- fail (printf "ssh-sidecar.sidecar: `sessionRoot` names %q but the mounts are %v. The declared path must be one of them, or the session opens on an empty directory that reads like missing data." $sessionPath $paths) -}}
{{- end -}}
{{- end -}}
- name: ssh
  image: {{ required "ssh-sidecar.sidecar: `image` is required, pinned to an exact version. It is a system value; see products/_lib/ssh-sidecar-image/README.md." .image | quote }}
  imagePullPolicy: IfNotPresent
  ports:
    - containerPort: 2222
  env:
    # The only key this server trusts. The tenant's own keys are checked by the
    # edge on the downstream leg, never here.
    - name: FREEPOD_AUTHORIZED_KEYS
      value: {{ $ssh.platformPublicKey | default "" | quote }}
    - name: FREEPOD_SESSION_ROOT
      value: {{ $sessionRoot | quote }}
    {{- if and $isApp $db.host $db.port }}
    # Rendered only for an application-rooted deployment that has a database,
    # because that endpoint is the only thing forwarded to. Absent, the server
    # writes `PermitOpen none` and refuses every forward.
    - name: FREEPOD_PERMIT_OPEN
      value: {{ printf "%s:%v" $db.host $db.port | quote }}
    {{- end }}
    - name: FREEPOD_RELEASE_ID
      value: {{ $caelus.releaseId | default "" | quote }}
    - name: FREEPOD_RELEASE_NUMBER
      value: {{ $caelus.releaseNumber | default "" | quote }}
    # The account the SSH edge authenticates the upstream leg as. The edge has
    # ONE username convention: the deployment name. This server needs uid 0, so the image adds the
    # deployment name as a second uid-0 account.
    - name: FREEPOD_LOGIN_USER
      value: {{ $root.Release.Name | quote }}
  {{- if $isApp }}
  {{- with $db.secretName }}
  envFrom:
    - secretRef:
        name: {{ . | quote }}
  {{- end }}
  {{- end }}
  {{- if $isVolume }}
  volumeMounts:
    {{- range .mounts }}
    - name: {{ .volume }}
      mountPath: {{ printf "%s%s" $jail .path | quote }}
      {{- if .subPath }}
      subPath: {{ .subPath }}
      {{- end }}
      readOnly: true
    {{- end }}
  {{- end }}
  securityContext:
    privileged: false
    allowPrivilegeEscalation: true
    runAsUser: 0
  startupProbe:
    tcpSocket:
      port: 2222
    periodSeconds: 2
    failureThreshold: 15
  # Every probe is a real connection that sshd forks a handler for and logs, and
  # that is nearly all an idle sidecar ever does. A minute between checks still
  # restarts a wedged server within a few minutes, which is soon enough for an
  # administrative side door.
  livenessProbe:
    tcpSocket:
      port: 2222
    periodSeconds: 60
    timeoutSeconds: 3
    failureThreshold: 3
  # Sized for the idle server every deployment carries, not for the rare session:
  # an idle sidecar measures about 1Mi, and the limit below still leaves a session
  # room to burst.
  resources:
    requests:
      cpu: 2m
      memory: 16Mi
    limits:
      # Headroom for `pg_dump`/`pg_restore`, which stream rather than buffer.
      memory: 256Mi
{{- end -}}
