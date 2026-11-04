package main

import (
	"errors"
	"net/http"
	"net/url"
	"strings"
	"testing"
)

// The Keycloak provider verifies these same vectors when its image is built
// (tf/deps/keycloak/provider/test/VectorCheck.java); change both together.
const (
	vectorSecret    = "vector-client-secret"
	vectorCatalog   = "eyJuYW1lIjoiSW1taWNoIiwiaG9zdCI6InBob3Rvcy1hbGljZS5mcmVlcG9kLmFwcCIsImljb24iOiJodHRwczovL2ZyZWVwb2QuZXUvYXBpL3N0YXRpYy9pY29ucy8yOTYxLnBuZyJ9.R5CfhT9TzIAYJiTcNZVsCxaIoS22uIPtkrrfUvvIDdQ"
	vectorHostOnly  = "eyJob3N0Ijoid2lraS1hbGljZS5mcmVlcG9kLmFwcCJ9.w_3fbkNO3n_vW3T1Q9voJJP-NZOKEZ8_ORG5Sr5fX8I"
	vectorIconPath  = "icons/2961.png"
	vectorPlatform  = "https://freepod.eu"
	vectorPhotoHost = "photos-alice.freepod.app"
	vectorWikiHost  = "wiki-alice.freepod.app"
)

func TestBrandSignsTheSharedVectors(t *testing.T) {
	immich := newAppBrand(vectorPhotoHost, product{Name: "Immich", Slug: "immich", IconPath: vectorIconPath}, vectorPlatform)
	if got := immich.sign(vectorSecret); got != vectorCatalog {
		t.Fatalf("catalog app signed as %s", got)
	}
	custom := newAppBrand(vectorWikiHost, product{Name: "Custom user app", Slug: customSlug, IconPath: "icons/c.png"}, vectorPlatform)
	if got := custom.sign(vectorSecret); got != vectorHostOnly {
		t.Fatalf("custom app signed as %s", got)
	}
}

func TestNewAppBrand(t *testing.T) {
	for name, tc := range map[string]struct {
		p        product
		platform string
		want     appBrand
	}{
		"catalog app":            {product{"Immich", "immich", "icons/i.png"}, "https://freepod.eu", appBrand{"Immich", "h", "https://freepod.eu/api/static/icons/i.png"}},
		"no platform URL":        {product{"Immich", "immich", "icons/i.png"}, "", appBrand{Name: "Immich", Host: "h"}},
		"no icon":                {product{"Immich", "immich", ""}, "https://freepod.eu", appBrand{Name: "Immich", Host: "h"}},
		"custom is its hostname": {product{"Custom user app", customSlug, "icons/c.png"}, "https://freepod.eu", appBrand{Host: "h"}},
		"product without a slug": {product{Name: "Admin's app"}, "", appBrand{Name: "Admin's app", Host: "h"}},
	} {
		if got := newAppBrand("h", tc.p, tc.platform); got != tc.want {
			t.Errorf("%s: %+v", name, got)
		}
	}
	if (appBrand{}).sign("s") != "" || (appBrand{Host: "h"}).sign("") != "" {
		t.Fatal("signed without a brand or a key")
	}
}

func TestKeycloakRequestCarriesTheBrand(t *testing.T) {
	p := newStubIdP(t)
	u, _ := p.auth().authURL("s", "n", "v", authParams{brand: appBrand{Host: "wiki.example"}})
	q, _ := url.ParseQuery(u[strings.Index(u, "?")+1:])
	if q.Get(brandParam) != (appBrand{Host: "wiki.example"}).sign("s") {
		t.Fatalf("authorization URL %s", u)
	}
	u, _ = p.auth().authURL("s", "n", "v", authParams{})
	if strings.Contains(u, brandParam) {
		t.Fatalf("unbranded authorization URL %s", u)
	}
}

func TestHeaderSignInIsBranded(t *testing.T) {
	g := newBrokerRig(t)
	g.b.platformURL = "https://freepod.example"
	g.st.products["dep-milk"] = product{Name: "Milk", Slug: "milk", IconPath: "icons/m.png"}
	g.start(milk)
	want := appBrand{Name: "Milk", Host: milk, Icon: "https://freepod.example/api/static/icons/m.png"}
	if g.auth.params.brand != want {
		t.Fatalf("%+v", g.auth.params.brand)
	}
}

func TestOIDCSignInIsBranded(t *testing.T) {
	g := newProviderRig(t)
	g.st.products[depWiki] = product{Name: "Custom user app", Slug: customSlug}
	g.authorize(authorizeQuery(depWiki, wikiCallback))
	if g.auth.params.brand != (appBrand{Host: wiki}) {
		t.Fatalf("%+v", g.auth.params.brand)
	}
}

func TestKeycloakLogoutCarriesTheBrand(t *testing.T) {
	p := newStubIdP(t)
	u, _ := p.auth().endSessionURL("s", "https://login.example/signed-out", appBrand{Host: "wiki.example"})
	q, _ := url.ParseQuery(u[strings.Index(u, "?")+1:])
	if q.Get(brandParam) != (appBrand{Host: "wiki.example"}).sign("s") {
		t.Fatalf("end-session URL %s", u)
	}
}

func TestHeaderSignOutIsBranded(t *testing.T) {
	g := newBrokerRig(t)
	g.st.products["dep-milk"] = product{Name: "Milk", Slug: "milk"}
	g.logout(milk, "/")
	if g.auth.logoutBrand != (appBrand{Name: "Milk", Host: milk}) {
		t.Fatalf("%+v", g.auth.logoutBrand)
	}
}

func TestOIDCSignOutIsBranded(t *testing.T) {
	root := "https://" + wiki + "/"
	for name, tc := range map[string]struct {
		params func(hint string) url.Values
		want   appBrand
	}{
		"by its ID token": {func(hint string) url.Values {
			return url.Values{"client_id": {depWiki}, "id_token_hint": {hint}, "post_logout_redirect_uri": {root}}
		}, appBrand{Name: "Wiki", Host: wiki}},
		"by the token alone": {func(hint string) url.Values {
			return url.Values{"id_token_hint": {hint}}
		}, appBrand{Name: "Wiki", Host: wiki}},
		"by client_id alone": {func(string) url.Values {
			return url.Values{"client_id": {depWiki}}
		}, appBrand{Name: "Wiki", Host: wiki}},
		"unknown client": {func(string) url.Values {
			return url.Values{"client_id": {"0b7f8d2e-4c1a-4e5b-9a3d-6f2e1c0b9aff"}}
		}, appBrand{}},
		"no client": {func(string) url.Values { return url.Values{} }, appBrand{}},
	} {
		t.Run(name, func(t *testing.T) {
			g := newProviderRig(t)
			g.st.products[depWiki] = product{Name: "Wiki", Slug: "wiki"}
			g.endSession(tc.params(g.redeem(depWiki, wikiCallback).IDToken))
			if g.auth.logoutBrand != tc.want {
				t.Fatalf("%+v", g.auth.logoutBrand)
			}
		})
	}
}

func TestOIDCSignOutSurvivesAFailedClientLookup(t *testing.T) {
	g := newProviderRig(t)
	g.st.clientErr = errors.New("database down")
	if w := g.do("GET", "/oidc/logout?"+url.Values{"client_id": {depWiki}}.Encode(), nil); w.Code != http.StatusFound || g.auth.endSessions != 1 {
		t.Fatalf("%d endSessions=%d", w.Code, g.auth.endSessions)
	}
}
