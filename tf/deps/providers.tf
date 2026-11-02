terraform {
  required_version = ">= 1.0"

  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.13"
    }
    # keycloak/keycloak is the maintained continuation of mrparkers/keycloak,
    # which has had no release since January 2024. Do not switch back.
    #
    # 5.8 and later need Keycloak 26 or newer: they send realm fields older
    # servers reject (keycloak/Dockerfile pins the server).
    keycloak = {
      source  = "keycloak/keycloak"
      version = "~> 5.10"
    }
  }
}

provider "kubernetes" {
  config_path = "../../k8s/kubeconfigs/dev-k3s.yaml"
}

provider "helm" {
  kubernetes {
    config_path = "../../k8s/kubeconfigs/dev-k3s.yaml"
  }
}

# Authenticates as the bootstrap instance administrator, which lives in the
# `master` realm (the provider's default login realm). It manages realm,
# client, client-scope and group configuration only — never end-user accounts.
provider "keycloak" {
  client_id = "admin-cli"
  username  = "admin"
  password  = var.keycloak_admin_password
  url       = var.keycloak_url
}
