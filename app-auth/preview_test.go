package main

import (
	"net"
	"net/http"
	"os"
	"testing"
)

// TestPreview serves every page with sample data, for design work:
//
//	APP_AUTH_PREVIEW=127.0.0.1:8099 go test -run TestPreview -timeout 0 .
//
// then open http://127.0.0.1:8099/. Skipped unless the variable is set.
func TestPreview(t *testing.T) {
	addr := os.Getenv("APP_AUTH_PREVIEW")
	if addr == "" {
		t.Skip("set APP_AUTH_PREVIEW=host:port to serve the page previews")
	}
	c := newChrome("http://" + addr)
	c.PlatformURL = "https://dev.freepod.eu"

	mux := http.NewServeMux()
	mux.Handle("GET /assets/", assetHandler())
	pages := map[string]func(w http.ResponseWriter){
		"/consent": func(w http.ResponseWriter) {
			renderConsent(w, consentView{chrome: c, Host: "milk.fred.dev.freepod.eu",
				Name: "Alice Ångström", Email: "alice@example.com",
				ShortSub: shortSub("3f2a91c0-5d7e-4b1a-9c3e-8f0d2b6a41e7"), CSRF: "x"})
		},
		"/consent-long": func(w http.ResponseWriter) {
			renderConsent(w, consentView{chrome: c, Host: "groceries-and-household-supplies.example-custom-domain.com",
				Email:    "a.very.long.email.address@subdomain.example.org",
				ShortSub: shortSub("3f2a91c0-5d7e-4b1a-9c3e-8f0d2b6a41e7"), CSRF: "x"})
		},
		"/declined": func(w http.ResponseWriter) {
			renderPage(w, 200, page{chrome: c, Kind: "done", Title: "Nothing was shared",
				Message: "milk.fred.dev.freepod.eu did not receive your name, email address or account identifier. You can close this page."})
		},
		"/unavailable": func(w http.ResponseWriter) {
			renderPage(w, 404, page{chrome: c, Title: "Sign-in isn't available here",
				Message: "evil.example does not offer Sign in with Freepod."})
		},
		"/unverified": func(w http.ResponseWriter) {
			renderPage(w, 403, page{chrome: c, Kind: "info", Title: "Verify your email first",
				Message: "Apps can only receive a verified email address. Open the verification email Freepod sent you, then sign in again."})
		},
		"/callback-failed": func(w http.ResponseWriter) {
			v := &verifier{loginURL: "http://" + addr}
			rec := &previewRecorder{ResponseWriter: w}
			v.failurePage(rec, "milk.fred.dev.freepod.eu")
		},
	}
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		for p := range pages {
			w.Write([]byte(`<p><a href="` + p + `">` + p + `</a></p>`))
		}
	})
	for p, render := range pages {
		mux.HandleFunc("GET "+p, func(w http.ResponseWriter, r *http.Request) { render(w) })
	}
	l, err := net.Listen("tcp", addr)
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("previews at http://%s/", addr)
	http.Serve(l, mux)
}

type previewRecorder struct{ http.ResponseWriter }
