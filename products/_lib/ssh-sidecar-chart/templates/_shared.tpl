{{- /*
ssh-sidecar library chart — what every deployment's SSH access shares.

The sidecar itself and what a session may do live in _sidecar.tpl and follow
from one declaration, `sessionRoot`. Everything in this file is independent of
that declaration. The Service especially: it is the one object the SSH edge
depends on, the edge knows nothing about session roots, and a second copy would
only ask two authors to keep agreeing.

All helpers take a dict; `root` is always the top-level chart context (needed
for .Release.* and cluster lookups).
*/}}

{{- /* Common labels for every SSH resource. */ -}}
{{- define "ssh-sidecar.labels" -}}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/managed-by: caelus
caelus.dev/component: ssh
{{- end -}}

{{- /*
ssh-sidecar.service — the Service fronting the sidecar. Whatever a deployment's
session is rooted at, it presents this same Service to the edge.

The name follows the platform's single naming convention, `<release>-ssh`,
which the SSH edge uses to derive a deployment's upstream address. **That
convention is shared with `daemons/ssh-auth/` and cannot be changed on one side
alone** — a chart rendering a name the edge does not expect produces a
deployment that authenticates and then reaches nothing, and the failure surfaces
at the edge rather than here. See daemons/ssh-auth/README.md § Coupling.

Params:
  serviceName  Service name (default "<release>-ssh"). Overriding it makes the
               deployment unroutable; there is no reason to.
  selector     Service pod selector (default: instance label). Products whose
               sidecar rides in an upstream subchart's pod MUST pass the
               labels of that pod.
*/}}
{{- define "ssh-sidecar.service" -}}
{{- $root := .root -}}
{{- $serviceName := .serviceName | default (printf "%s-ssh" $root.Release.Name) -}}
apiVersion: v1
kind: Service
metadata:
  name: {{ $serviceName }}
  labels:
    {{- include "ssh-sidecar.labels" (dict "root" $root) | nindent 4 }}
spec:
  # The sidecar fronts administration, not the application. Its usefulness peaks
  # when the app container is broken, so application readiness must not gate
  # routing here. Do not drop this: its loss is silent until an app crash-loops.
  publishNotReadyAddresses: true
  selector:
    {{- include "ssh-sidecar.podSelector" (dict "root" $root "selector" .selector) | nindent 4 }}
  ports:
    - name: ssh
      protocol: TCP
      port: 2222
      targetPort: 2222
{{- end -}}

{{- /*
ssh-sidecar.podSelector — labels the Service uses to find the sidecar's pod.
Products whose sidecar rides in the upstream subchart's pod MUST override this
by passing `selector` (a dict of label:value) so the Service targets that pod;
otherwise it defaults to the standard Caelus instance label.
*/}}
{{- define "ssh-sidecar.podSelector" -}}
{{- if .selector -}}
{{- range $k, $v := .selector }}
{{ $k }}: {{ $v | quote }}
{{- end -}}
{{- else -}}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}
{{- end -}}
