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
	immich := newAppBrand(vectorPhotoHost, appIdentity{Name: "Immich", IconPath: vectorIconPath}, vectorPlatform)
	if got := immich.sign(vectorSecret); got != vectorCatalog {
		t.Fatalf("named app signed as %s", got)
	}
	unread := newAppBrand(vectorWikiHost, appIdentity{}, vectorPlatform)
	if got := unread.sign(vectorSecret); got != vectorHostOnly {
		t.Fatalf("unnamed app signed as %s", got)
	}
}

func TestNewAppBrand(t *testing.T) {
	for name, tc := range map[string]struct {
		id       appIdentity
		platform string
		want     appBrand
	}{
		"named app":       {appIdentity{"Family photos", "icons/i.png"}, "https://freepod.eu", appBrand{"Family photos", "h", "https://freepod.eu/api/static/icons/i.png"}},
		"no platform URL": {appIdentity{"Immich", "icons/i.png"}, "", appBrand{Name: "Immich", Host: "h"}},
		"no icon":         {appIdentity{"Immich", ""}, "https://freepod.eu", appBrand{Name: "Immich", Host: "h"}},
		"unread identity": {appIdentity{}, "https://freepod.eu", appBrand{Host: "h"}},
	} {
		if got := newAppBrand("h", tc.id, tc.platform); got != tc.want {
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
	g.st.identities["dep-milk"] = appIdentity{Name: "Milk", IconPath: "icons/m.png"}
	g.start(milk)
	want := appBrand{Name: "Milk", Host: milk, Icon: "https://freepod.example/api/static/icons/m.png"}
	if g.auth.params.brand != want {
		t.Fatalf("%+v", g.auth.params.brand)
	}
}

func TestOIDCSignInIsBranded(t *testing.T) {
	g := newProviderRig(t)
	g.st.identities[depWiki] = appIdentity{Name: "Wiki"}
	g.authorize(authorizeQuery(depWiki, wikiCallback))
	if g.auth.params.brand != (appBrand{Name: "Wiki", Host: wiki}) {
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
	g.st.identities["dep-milk"] = appIdentity{Name: "Milk"}
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
			g.st.identities[depWiki] = appIdentity{Name: "Wiki"}
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

func TestHeaderConsentNamesTheAppBesideItsHostname(t *testing.T) {
	g := newBrokerRig(t)
	g.b.platformURL = "https://freepod.example"
	g.st.identities["dep-milk"] = appIdentity{Name: "Milk <run>", IconPath: "icons/m.png"}
	w := g.returnFromIdP(g.start(milk))
	body := w.Body.String()
	for _, want := range []string{
		`Continue to <span class="host">Milk &lt;run&gt;</span>?`,
		`<p class="app-host">` + milk + `</p>`,
		`<img class="app-icon" src="https://freepod.example/api/static/icons/m.png" alt="">`,
		`<title>Continue to Milk &lt;run&gt; · Freepod</title>`,
	} {
		if !strings.Contains(body, want) {
			t.Fatalf("missing %q in %s", want, body)
		}
	}
	if csp := w.Header().Get("Content-Security-Policy"); !strings.Contains(csp, "img-src 'self' https://freepod.example;") {
		t.Fatalf("CSP %s", csp)
	}
}

func TestOIDCConsentWithoutAnIconShowsTheInitial(t *testing.T) {
	g := newProviderRig(t)
	g.st.identities[depWiki] = appIdentity{Name: "wiki"}
	w := g.returnFromIdP(g.authorize(authorizeQuery(depWiki, wikiCallback)))
	body := w.Body.String()
	if !strings.Contains(body, `<div class="app-icon app-initial" aria-hidden="true">W</div>`) ||
		!strings.Contains(body, `<p class="app-host">`+wiki+`</p>`) {
		t.Fatalf("%s", body)
	}
	if csp := w.Header().Get("Content-Security-Policy"); !strings.Contains(csp, "img-src 'self';") {
		t.Fatalf("CSP %s", csp)
	}
}

func TestConsentFallsBackToTheHostname(t *testing.T) {
	g := newBrokerRig(t)
	body := g.returnFromIdP(g.start(milk)).Body.String()
	if !strings.Contains(body, `Continue to <span class="host">`+milk+`</span>?`) || strings.Contains(body, "app-host") {
		t.Fatalf("%s", body)
	}
}
