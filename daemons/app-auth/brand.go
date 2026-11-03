package main

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
)

// brandParam carries the app a sign-in is for to Keycloak, whose Freepod
// provider shows it on the sign-in pages and in the emails of that flow
// (tf/deps/keycloak/provider). Keycloak shows nothing it cannot verify, so the
// value is signed with a key derived from this broker's client secret, which
// Keycloak holds too.
const (
	brandParam    = "freepod_app"
	brandKeyLabel = "freepod-app-context:v1"
	// customSlug is the catalog product whose deployments carry the tenant's
	// own code under one shared name, so they are shown by hostname instead.
	customSlug = "custom"
)

// product is the catalog product a deployment runs, as far as branding needs it.
type product struct {
	Name     string
	Slug     string
	IconPath string // under the platform's /api/static/
}

// appBrand is what Keycloak may say about the app: a catalog app by its own
// name and icon, any other by its hostname alone.
type appBrand struct {
	Name string `json:"name,omitempty"`
	Host string `json:"host,omitempty"`
	Icon string `json:"icon,omitempty"`
}

// brand looks up the deployment's product for Keycloak. Branding is never
// worth a failed sign-in: without the product, the app is shown by hostname.
func (b *broker) brand(ctx context.Context, deploymentID, host string) appBrand {
	p, err := b.store.product(ctx, deploymentID)
	if err != nil {
		b.log.Warn("signing in without the app's name", "deployment", deploymentID, "err", err)
	}
	return newAppBrand(host, p, b.platformURL)
}

func newAppBrand(host string, p product, platformURL string) appBrand {
	if p.Name == "" || p.Slug == customSlug {
		return appBrand{Host: host}
	}
	b := appBrand{Name: p.Name, Host: host}
	if p.IconPath != "" && platformURL != "" {
		b.Icon = platformURL + "/api/static/" + p.IconPath
	}
	return b
}

// sign returns `<b64url(json)>.<b64url(hmac)>`, keyed by
// HMAC-SHA256(clientSecret, brandKeyLabel), or "" for an empty brand.
func (b appBrand) sign(clientSecret string) string {
	if b == (appBrand{}) || clientSecret == "" {
		return ""
	}
	raw, err := json.Marshal(b)
	if err != nil {
		return ""
	}
	payload := base64.RawURLEncoding.EncodeToString(raw)
	return payload + "." + base64.RawURLEncoding.EncodeToString(hmacSHA256(hmacSHA256([]byte(clientSecret), []byte(brandKeyLabel)), []byte(payload)))
}

func hmacSHA256(key, data []byte) []byte {
	h := hmac.New(sha256.New, key)
	h.Write(data)
	return h.Sum(nil)
}
