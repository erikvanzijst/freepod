# syntax=docker/dockerfile:1
#
# Every platform Go daemon, one static binary per daemons/<name>/ at /<name>,
# on scratch. No ENTRYPOINT or CMD: each consumer names the binary it runs.
#
# Immutable version tag from VERSION, never re-pushed: each consumer pins its
# own version in Terraform, and rolling back means pointing it at an earlier one.
FROM golang:1.25-bookworm AS build

# Each daemon is its own module and builds against its own go.mod; go.work is
# for editors only.
ENV GOWORK=off CGO_ENABLED=0

WORKDIR /src
COPY --parents */go.mod */go.sum ./
RUN for mod in */go.mod; do (cd "$(dirname "$mod")" && go mod download) || exit 1; done
COPY . .

# -s -w drops the symbol table and DWARF, which nothing in the pod can read.
RUN mkdir /out && for mod in */go.mod; do \
      d=$(dirname "$mod"); \
      (cd "$d" && go build -trimpath -ldflags="-s -w" -o "/out/$d" .) || exit 1; \
    done

FROM scratch
# For daemons that call out over HTTPS (app-auth's broker to Keycloak).
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=build /out/ /

USER 65534:65534
