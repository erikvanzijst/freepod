package main

import (
	"encoding/base64"
	"strings"
	"testing"
)

// The fingerprint is the join key between what sshpiperd hands us and what the
// API stored, so the two implementations have to agree byte for byte. These
// expectations come from `ssh-keygen -lf` on the same keys.
func TestFingerprintMatchesSshKeygen(t *testing.T) {
	for _, tc := range []struct {
		line string
		want string
	}{
		{
			"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBZO/CpZb1FS9RnxIaTPPPAIrDvHCcynnYjhA7Jkvgw/",
			"SHA256:NZwWqsGv4mBvnSdpTnzetR1qEiBEr6tOgEAWH1mI8sM",
		},
		{
			"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIV5/SURDe/M7JtAheJuxURSGgpFB8Yfrd/LY6c9+DzR",
			"SHA256:0fSPF2sIla+XxGC9I+hfE8GLJndu6jp1Ne6bigu5tWk",
		},
	} {
		blob, err := base64.StdEncoding.DecodeString(strings.Fields(tc.line)[1])
		if err != nil {
			t.Fatal(err)
		}
		if got := fingerprint(blob); got != tc.want {
			t.Errorf("fingerprint = %q, want %q", got, tc.want)
		}
	}
}

// An allowlist, and `error` is in it: file access matters most when the
// application is broken, and excluding it would re-create the D17 defect one
// layer up. This must never become a passing denial.
func TestReachabilityAllowlist(t *testing.T) {
	for status, want := range map[string]bool{
		"ready": true, "error": true,
		"pending": false, "provisioning": false, "deleting": false, "deleted": false,
		"something-added-later": false,
	} {
		if reachable[status] != want {
			t.Errorf("reachable[%q] = %v, want %v", status, reachable[status], want)
		}
	}
}
