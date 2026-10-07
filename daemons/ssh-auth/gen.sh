#!/bin/bash
#
# Regenerate the protobuf stubs from the vendored plugin.proto.
#
# The stubs are checked in, so this is not part of the build: it is the step to
# run when the pinned sshpiperd version changes. `proto_test.go` regenerates
# them into a temporary directory and compares byte for byte, so a forgotten run
# is a test failure rather than a runtime surprise.
#
# Re-vendoring the proto is a separate, deliberate act -- see proto/UPSTREAM.
#
# Every tool is pinned and fetched into ./.tools, which is gitignored. This
# directory depends on nothing else in the repository, and the byte-for-byte
# check only means something if everyone's toolchain is the same one.

set -euo pipefail

cd "$(dirname "$0")"

PROTOC_VERSION=36.0
PROTOC_GEN_GO_VERSION=v1.36.6
PROTOC_GEN_GO_GRPC_VERSION=v1.5.1

TOOLS="$PWD/.tools"
PROTOC="$TOOLS/protoc-$PROTOC_VERSION/bin/protoc"
PKG=github.com/erikvanzijst/caelus/ssh-auth/internal/libplugin

if [ ! -x "$PROTOC" ]; then
  echo "Fetching protoc $PROTOC_VERSION..."
  mkdir -p "$TOOLS/protoc-$PROTOC_VERSION"
  curl -sSLo "$TOOLS/protoc.zip" \
    "https://github.com/protocolbuffers/protobuf/releases/download/v${PROTOC_VERSION}/protoc-${PROTOC_VERSION}-linux-x86_64.zip"
  unzip -q -o "$TOOLS/protoc.zip" -d "$TOOLS/protoc-$PROTOC_VERSION"
  rm -f "$TOOLS/protoc.zip"
fi

# GOBIN rather than the ambient GOPATH/bin, so a differently-versioned plugin
# already on the machine cannot change what this emits.
GOBIN="$TOOLS/bin" go install "google.golang.org/protobuf/cmd/protoc-gen-go@$PROTOC_GEN_GO_VERSION"
GOBIN="$TOOLS/bin" go install "google.golang.org/grpc/cmd/protoc-gen-go-grpc@$PROTOC_GEN_GO_GRPC_VERSION"

"$PROTOC" \
  --proto_path=proto \
  --plugin=protoc-gen-go="$TOOLS/bin/protoc-gen-go" \
  --plugin=protoc-gen-go-grpc="$TOOLS/bin/protoc-gen-go-grpc" \
  --go_out=internal/libplugin --go_opt=paths=source_relative \
  --go_opt=Mplugin.proto=$PKG \
  --go-grpc_out=internal/libplugin --go-grpc_opt=paths=source_relative \
  --go-grpc_opt=Mplugin.proto=$PKG \
  plugin.proto

echo "Regenerated internal/libplugin/plugin*.pb.go"
