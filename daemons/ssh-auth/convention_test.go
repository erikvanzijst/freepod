package main

import (
	"os/exec"
	"strings"
	"testing"
)

// The upstream address convention is shared with the product charts, and the
// coupling is invisible from either side: this package names a Service it never
// validates, and a chart names a Service nothing in its own release consults.
// A unilateral change to either produces deployments that authenticate and then
// reach nothing, and the failure surfaces at the edge rather than where the
// change was made.
//
// So this renders a real product chart and compares what it emits against what
// the resolver derives for the same deployment name. It is the only test in
// either repository half that would fail if one side moved alone.
//
// Both session roots are checked. `helloworld` declares a volume root and
// `custom` an application-container one; the edge is deliberately ignorant of
// that difference, so a Service that varied by session root would be a routing
// bug this catches at build time.
func TestChartsRenderTheServiceNameTheResolverDerives(t *testing.T) {
	helm, err := exec.LookPath("helm")
	if err != nil {
		t.Skip("helm not installed")
	}

	// What the resolver derives, in the same shape resolve.go builds it. The
	// query is `d.name || '-ssh.' || d.namespace || '.svc'`, so the Service's
	// own name -- the half a chart controls -- is `<release>-ssh`.
	const release = "hello-world-aaa111"
	want := release + "-ssh"

	for _, c := range []struct {
		name  string
		chart string
		args  []string
	}{
		{
			name:  "volume session root",
			chart: "../../products/helloworld/chart",
			args: []string{
				"--set-string", "caelus.ssh.platformPublicKey=" + platformKeyLine,
			},
		},
		{
			name:  "application-container session root",
			chart: "../../products/custom/chart",
			args: []string{
				"--set-string", "caelus.ssh.platformPublicKey=" + platformKeyLine,
				"--set", "hostname=app.example.test",
				"--set", "caelus.owner.id=1",
				"--set", "relationalStorage.enabled=true",
				"--set", "caelus.database.host=pooler.example",
				"--set", "caelus.database.port=6432",
				"--set", "caelus.database.secretName=db",
			},
		},
	} {
		t.Run(c.name, func(t *testing.T) {
			if out, err := exec.Command(helm, "dependency", "build", c.chart).CombinedOutput(); err != nil {
				t.Fatalf("helm dependency build: %v\n%s", err, out)
			}
			args := append([]string{"template", release, c.chart}, c.args...)
			out, err := exec.Command(helm, args...).CombinedOutput()
			if err != nil {
				t.Fatalf("helm template: %v\n%s", err, out)
			}
			if !strings.Contains(string(out), "name: "+want+"\n") {
				t.Errorf("a chart with a %s renders no Service named %q, which is "+
					"the address this resolver dials. One side of the shared naming "+
					"convention moved without the other; see resolve.go and "+
					"products/_lib/ssh-sidecar-chart/README.md.", c.name, want)
			}
		})
	}
}

const platformKeyLine = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIV5/SURDe/M7JtAheJuxURSGgpFB8Yfrd/LY6c9+DzR platform"
