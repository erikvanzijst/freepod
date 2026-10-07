package main

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	pb "github.com/erikvanzijst/caelus/ssh-auth/internal/libplugin"
	"google.golang.org/protobuf/reflect/protoreflect"
)

// The proto is vendored verbatim from sshpiper; see proto/UPSTREAM. Bumping the
// sshpiperd image means re-vendoring, regenerating, and updating these two
// constants -- in that order, and none of the three on its own.
const (
	expectedProtoSHA256 = "1c11ca0b75a1fc06ae6f721724b56106110bc5f57e3a7924cb1357dc796ea178"
	expectedTag         = "v1.5.4"

	// Must match ./gen.sh. A different protoc serializes the descriptor these
	// stubs embed differently, so the byte-for-byte check is only a drift
	// detector while both use the same one.
	protocVersion = "36.0"
)

var generated = []string{"plugin.pb.go", "plugin_grpc.pb.go"}

func TestVendoredProtoIsThePinnedUpstreamFile(t *testing.T) {
	raw, err := os.ReadFile("proto/plugin.proto")
	if err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(raw)
	if got := hex.EncodeToString(sum[:]); got != expectedProtoSHA256 {
		t.Fatalf("proto/plugin.proto is not the file UPSTREAM names (%s).\n"+
			"Re-vendor it, run ./gen.sh, and update expectedProtoSHA256 here "+
			"together with UPSTREAM.", got)
	}
}

func TestUpstreamNoteRecordsTheSamePin(t *testing.T) {
	note, err := os.ReadFile("proto/UPSTREAM")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{expectedProtoSHA256, expectedTag} {
		if !strings.Contains(string(note), want) {
			t.Errorf("proto/UPSTREAM does not record %q", want)
		}
	}
}

// The shape this resolver hardwires itself against, read out of the descriptor
// the generated code embeds. It is the cheap half of the drift check and needs
// no toolchain: a regeneration from some *other* proto would still compile,
// and this is what notices.
func TestGeneratedDescriptorMatchesWhatTheResolverAssumes(t *testing.T) {
	file := (&pb.Upstream{}).ProtoReflect().Descriptor().ParentFile()

	svc := file.Services().ByName("SshPiperPlugin")
	if svc == nil {
		t.Fatal("SshPiperPlugin service is missing")
	}
	for _, name := range []string{"ListCallbacks", "PublicKeyAuth", "Logs"} {
		if svc.Methods().ByName(protoreflect.Name(name)) == nil {
			t.Errorf("%s RPC is missing; this resolver implements it", name)
		}
	}

	up := file.Messages().ByName("Upstream")
	for _, name := range []string{"user_name", "uri", "ignore_host_key"} {
		if up.Fields().ByName(protoreflect.Name(name)) == nil {
			t.Errorf("Upstream.%s is missing; the resolver sets it", name)
		}
	}
	// v1.5.4 has no `known_hosts_data`. If a later revision adds one, host-key
	// handling is worth revisiting rather than silently keeping
	// ignore_host_key -- so notice it here rather than in an incident.
	if up.Fields().ByName("known_hosts_data") != nil {
		t.Error("Upstream.known_hosts_data now exists; revisit ignore_host_key")
	}
	if up.Oneofs().ByName("auth").Fields().ByName("private_key") == nil {
		t.Error("Upstream.auth has no private_key member")
	}
}

// The expensive half, and the exact one: regenerate into a scratch tree and
// compare byte for byte. Every tool is pinned and fetched by ./gen.sh into
// ./.tools, so this is skipped until that has been run once rather than failing
// a fresh checkout; the descriptor test above still runs everywhere.

func TestCheckedInStubsMatchAFreshGeneration(t *testing.T) {
	tools, err := filepath.Abs(".tools")
	if err != nil {
		t.Fatal(err)
	}
	protoc := filepath.Join(tools, "protoc-"+protocVersion, "bin", "protoc")
	needed := []string{protoc,
		filepath.Join(tools, "bin", "protoc-gen-go"),
		filepath.Join(tools, "bin", "protoc-gen-go-grpc")}
	for _, tool := range needed {
		if _, err := os.Stat(tool); err != nil {
			t.Skipf("%s is not present; run ./gen.sh once for the exact check", tool)
		}
	}

	out := t.TempDir()
	const pkg = "github.com/erikvanzijst/caelus/ssh-auth/internal/libplugin"
	cmd := exec.Command(protoc,
		"--proto_path=proto",
		"--plugin=protoc-gen-go="+filepath.Join(tools, "bin", "protoc-gen-go"),
		"--plugin=protoc-gen-go-grpc="+filepath.Join(tools, "bin", "protoc-gen-go-grpc"),
		"--go_out="+out, "--go_opt=paths=source_relative", "--go_opt=Mplugin.proto="+pkg,
		"--go-grpc_out="+out, "--go-grpc_opt=paths=source_relative", "--go-grpc_opt=Mplugin.proto="+pkg,
		"plugin.proto")
	if output, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("protoc: %v\n%s", err, output)
	}

	for _, name := range generated {
		fresh, err := os.ReadFile(filepath.Join(out, name))
		if err != nil {
			t.Fatal(err)
		}
		checkedIn, err := os.ReadFile(filepath.Join("internal", "libplugin", name))
		if err != nil {
			t.Fatal(err)
		}
		if string(fresh) != string(checkedIn) {
			t.Errorf("internal/libplugin/%s is not what the vendored proto generates. "+
				"Run ./gen.sh and commit the result.", name)
		}
	}
}
