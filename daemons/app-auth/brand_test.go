package main

import (
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
