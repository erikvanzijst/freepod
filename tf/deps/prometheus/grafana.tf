resource "kubernetes_secret" "grafana_oidc" {
  metadata {
    name      = "grafana-oidc"
    namespace = var.namespace
  }

  data = {
    client_secret = var.grafana_oidc_client_secret
  }

  type = "Opaque"
}

resource "helm_release" "grafana" {
  name       = "grafana"
  namespace  = var.namespace
  repository = "https://grafana.github.io/helm-charts"
  chart      = "grafana"
  version    = "9.4.4"

  values = [
    yamlencode({
      # Break-glass local admin. Day-to-day auth is Keycloak OIDC (below); the
      # whitelist is Keycloak group membership, not a Grafana user list.
      adminUser     = "admin"
      adminPassword = var.grafana_admin_password

      # The chart's init-chown-data container runs as UID 472 and cannot chown
      # the PVC once Grafana has populated it (files already owned by 472) — it
      # CrashLoops on every redeploy with "Permission denied". fsGroup=472
      # already grants the main container write access, so this init is both
      # unnecessary and harmful here.
      initChownData = {
        enabled = false
      }

      "grafana.ini" = {
        server = {
          root_url = "https://${var.grafana_domain}/"
        }

        auth = {
          oauth_allow_insecure_email_lookup = true
        }

        # Native Keycloak OIDC. Access is restricted to members of the
        # `freepod-observability` Keycloak group: allowed_groups gates login and
        # role_attribute_strict denies anyone the JMESPath maps to no role.
        #
        # NOTE: no `use_pkce` here, and correspondingly no
        # pkce_code_challenge_method on the `grafana` client in
        # ../keycloak-config/clients.tf. Grafana only sends a code challenge
        # when use_pkce = true; setting the client attribute alone makes PKCE
        # mandatory at Keycloak and fails every Grafana login. The two are a
        # matched pair — enable both together or neither. (The oauth2-proxy
        # clients DO require PKCE, and set --code-challenge-method to match.)
        "auth.generic_oauth" = {
          enabled              = true
          name                 = "Keycloak"
          client_id            = var.grafana_oidc_client_id
          client_secret        = "$__env{GRAFANA_OAUTH_CLIENT_SECRET}"
          scopes               = "openid email profile groups"
          auth_url             = "${var.keycloak_url}/realms/${var.keycloak_realm}/protocol/openid-connect/auth"
          token_url            = "${var.keycloak_url}/realms/${var.keycloak_realm}/protocol/openid-connect/token"
          api_url              = "${var.keycloak_url}/realms/${var.keycloak_realm}/protocol/openid-connect/userinfo"
          login_attribute_path = "preferred_username"
          email_attribute_path = "email"
          # REQUIRED for allowed_groups to work: Grafana's extractGroups() returns
          # an empty list unless groups_attribute_path is set, so without this the
          # groups claim (present in the token) is never read and every login is
          # rejected as "not a member of one of the required groups".
          groups_attribute_path = "groups"
          allowed_groups        = "freepod-observability"
          role_attribute_path   = "contains(groups[*], 'freepod-observability') && 'Admin' || ''"
          role_attribute_strict = true
        }
      }

      # Inject the OIDC client secret as an env var sourced from the Secret above.
      # grafana.ini reads it via $__env{GRAFANA_OAUTH_CLIENT_SECRET}.
      envValueFrom = {
        GRAFANA_OAUTH_CLIENT_SECRET = {
          secretKeyRef = {
            name = kubernetes_secret.grafana_oidc.metadata[0].name
            key  = "client_secret"
          }
        }
      }

      service = {
        type = "ClusterIP"
        port = 80
      }

      persistence = {
        enabled = true
        size    = "5Gi"
      }

      datasources = {
        "datasources.yaml" = {
          apiVersion = 1
          datasources = [
            {
              name      = "Prometheus"
              type      = "prometheus"
              url       = "http://prometheus-server.${var.namespace}.svc.cluster.local"
              access    = "proxy"
              isDefault = true
              # MUST match Prometheus's global scrape_interval (prometheus.tf).
              # Grafana floors $__rate_interval at 4x this value; leaving it unset
              # defaults to 15s, so with a 60s scrape the floor (60s) holds only
              # ~1 sample and irate()-based panels (Node Exporter Full's CPU
              # Basic, Network Basic, Forks, schedstat) render empty on wide/
              # high-resolution panels. 60s -> 240s floor -> >=4 samples.
              jsonData = {
                timeInterval = "60s"
              }
            },
            {
              name      = "Loki"
              type      = "loki"
              url       = "http://loki.${var.namespace}.svc.cluster.local:3100"
              access    = "proxy"
              isDefault = false
            }
          ]
        }
      }

      # Provision dashboards as code so a fresh apply comes up populated. gnetId
      # dashboards are fetched from grafana.com at pod start.
      # NOTE: `revision` is pinned — verify/bump against the latest at
      # https://grafana.com/grafana/dashboards/<id> when updating.
      dashboardProviders = {
        "dashboardproviders.yaml" = {
          apiVersion = 1
          providers = [
            {
              name            = "default"
              orgId           = 1
              folder          = ""
              type            = "file"
              disableDeletion = false
              editable        = true
              options = {
                path = "/var/lib/grafana/dashboards/default"
              }
            }
          ]
        }
      }

      dashboards = {
        default = {
          "node-exporter-full" = {
            gnetId     = 1860
            revision   = 37
            datasource = "Prometheus"
          }
          # Traefik Official Kubernetes Dashboard (Traefik Labs). Chosen over
          # 25330 "NextGen", which filters every panel by a `host` label that
          # Traefik v3 does not emit (→ all-N/A). 17347 keys off entrypoint/
          # service labels we actually have, uses only v3 metric names, and is
          # the most-adopted maintained official option.
          "traefik-official-k8s" = {
            gnetId     = 17347
            revision   = 9
            datasource = "Prometheus"
          }
        }
      }
    })
  ]
}
