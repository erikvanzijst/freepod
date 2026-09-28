# app-auth: "Sign in with Freepod" for tenant apps -- the Traefik forward-auth
# verifier and the login-host broker, one static binary on scratch.
#
# Immutable version tag from VERSION, never re-pushed: rolling back means
# pointing Terraform at the previous version.
FROM golang:1.25-bookworm AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .

RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /app-auth .

FROM scratch
# The broker calls Keycloak over HTTPS.
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=build /app-auth /app-auth

USER 65534:65534
EXPOSE 8080 8081
ENTRYPOINT ["/app-auth"]
