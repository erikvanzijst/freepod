package main

import (
	"crypto/sha256"
	"embed"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"html/template"
	"io/fs"
	"net/http"
	"net/url"
	"strings"
	"unicode"
	"unicode/utf8"
)

// The broker's and verifier's own pages, in the skin of the Keycloak theme
// they follow (assets/app-auth.css). Fonts, logo and stylesheet are embedded
// and served by the broker at /assets/; nothing is loaded from a third party.
//
//go:embed assets
var assetFS embed.FS

// assetHandler serves the embedded assets. Fonts are fetched cross-origin by
// the verifier's page, which renders on an app's host, so they carry CORS.
func assetHandler() http.Handler {
	sub, err := fs.Sub(assetFS, "assets")
	if err != nil {
		panic(err)
	}
	files := http.StripPrefix("/assets/", http.FileServer(http.FS(sub)))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/") {
			http.NotFound(w, r)
			return
		}
		if strings.HasSuffix(r.URL.Path, ".woff2") {
			w.Header().Set("Content-Type", "font/woff2")
		}
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Cache-Control", "public, max-age=86400")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		files.ServeHTTP(w, r)
	})
}

const layout = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta name="robots" content="noindex">
<title>{{.Title}} · Freepod</title>
<link rel="icon" href="{{.Assets}}/logo.svg" type="image/svg+xml">
<link rel="stylesheet" href="{{.Assets}}/app-auth.css?v={{.CSSVersion}}">
</head><body><div class="page">
<a class="brand" href="{{.PlatformURL}}"><img src="{{.Assets}}/logo.svg" alt=""><span>Freepod</span></a>
<main class="card">{{template "body" .}}</main>
<div class="footer">Sign in with Freepod{{if .PlatformURL}} · <a href="{{.PlatformURL}}/legal/privacy">Privacy</a>{{end}}</div>
</div></body></html>`

const (
	iconUser   = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/></svg>`
	iconMail   = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="m4 7 8 6 8-6"/></svg>`
	iconKey    = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3M14 9l2 2"/></svg>`
	iconShield = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6L12 3z"/><path d="M12 8v4.5M12 16h.01"/></svg>`
	iconAlert  = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5M12 16.5h.01"/></svg>`
	iconInfo   = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.5h.01"/></svg>`
	iconDone   = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5 10 17l9-10"/></svg>`
)

var funcs = template.FuncMap{
	"icon": func(name string) template.HTML {
		return template.HTML(map[string]string{
			"user": iconUser, "mail": iconMail, "key": iconKey, "shield": iconShield,
			"error": iconAlert, "info": iconInfo, "done": iconDone,
		}[name])
	},
}

// mustPage returns the layout, with body defined inside it. (Parsing body with
// .New returns the body template itself, which renders without the layout.)
func mustPage(body string) *template.Template {
	t := template.Must(template.New("layout").Funcs(funcs).Parse(layout))
	template.Must(t.New("body").Parse(body))
	return t
}

var pageTmpl = mustPage(`
<div class="badge badge-{{.Kind}}">{{icon .Kind}}</div>
<p class="eyebrow">{{.Eyebrow}}</p>
<h1>{{.Title}}</h1>
<p>{{.Message}}</p>
{{if .Link}}<div class="actions"><a class="btn btn-primary" href="{{.Link}}">{{.LinkText}}</a></div>{{end}}`)

var consentTmpl = mustPage(`
<p class="eyebrow">Sign in with Freepod</p>
<h1>Continue to <span class="host">{{.Host}}</span>?</h1>
<div class="who">
  <div class="avatar" aria-hidden="true">{{.Initial}}</div>
  <div class="ident">
    <div class="name">{{if .Name}}{{.Name}}{{else}}{{.Email}}{{end}}</div>
    {{if .Name}}<div class="email">{{.Email}}</div>{{end}}
  </div>
  <div class="tag">Signed in</div>
</div>
<p class="section-label">This app will receive</p>
<ul class="grants">
  <li><span class="icon">{{icon "user"}}</span><span><span class="what">Your name</span><span class="value">{{if .Name}}{{.Name}}{{else}}Not set in your account{{end}}</span></span></li>
  <li><span class="icon">{{icon "mail"}}</span><span><span class="what">Your email address</span><span class="value">{{.Email}}</span></span></li>
  <li><span class="icon">{{icon "key"}}</span><span><span class="what">A permanent account identifier</span><span class="value mono">{{.ShortSub}}</span></span></li>
</ul>
<div class="callout">{{icon "shield"}}<div><strong>This app is run by a Freepod user, not by Freepod.</strong> What it does with your details is up to its operator.</div></div>
<form method="post" action="/consent">
  <input type="hidden" name="csrf" value="{{.CSRF}}">
  <div class="actions">
    <button class="btn btn-primary" type="submit" name="decision" value="allow">Continue</button>
    <button class="btn btn-ghost" type="submit" name="decision" value="deny">Cancel</button>
  </div>
</form>
<p class="fineprint">You'll only be asked once for this app.</p>`)

// cssVersion busts the day-long asset cache whenever the stylesheet changes.
var cssVersion = func() string {
	b, err := assetFS.ReadFile("assets/app-auth.css")
	if err != nil {
		panic(err)
	}
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:6])
}()

// chrome is what every page needs to find its assets and its way home.
type chrome struct {
	Assets      string // absolute: the verifier's page renders on an app host
	PlatformURL string // https://<domain>
}

func (chrome) CSSVersion() string { return cssVersion }

func newChrome(loginURL string) chrome {
	c := chrome{Assets: loginURL + "/assets"}
	if u, err := url.Parse(loginURL); err == nil {
		c.PlatformURL = u.Scheme + "://" + strings.TrimPrefix(u.Host, "login.")
	}
	return c
}

type page struct {
	chrome
	Kind     string // error | info | done
	Eyebrow  string
	Title    string
	Message  string
	Link     string
	LinkText string
}

type consentView struct {
	chrome
	Title    string
	Host     string
	Email    string
	Name     string
	Initial  string
	ShortSub string
	CSRF     string
}

func securityHeaders(w http.ResponseWriter, c chrome) {
	origin := "'self'"
	if u, err := url.Parse(c.Assets); err == nil && u.Host != "" {
		origin = u.Scheme + "://" + u.Host
	}
	h := w.Header()
	h.Set("Content-Type", "text/html; charset=utf-8")
	h.Set("Cache-Control", "no-store")
	h.Set("X-Frame-Options", "DENY")
	h.Set("X-Content-Type-Options", "nosniff")
	// form-action allows https: because the consent POST answers with a
	// redirect to the app's host, and browsers apply form-action to redirects.
	h.Set("Content-Security-Policy", "default-src 'none'; style-src "+origin+"; font-src "+origin+
		"; img-src "+origin+"; form-action 'self' https:; frame-ancestors 'none'; base-uri 'none'")
	h.Set("Referrer-Policy", "no-referrer")
}

func renderPage(w http.ResponseWriter, status int, p page) {
	if p.Kind == "" {
		p.Kind = "error"
	}
	if p.Eyebrow == "" {
		p.Eyebrow = "Sign in with Freepod"
	}
	securityHeaders(w, p.chrome)
	w.WriteHeader(status)
	pageTmpl.Execute(w, p)
}

func renderConsent(w http.ResponseWriter, v consentView) {
	v.Title = "Continue to " + v.Host
	v.Initial = initial(v.Name, v.Email)
	securityHeaders(w, v.chrome)
	w.WriteHeader(http.StatusOK)
	consentTmpl.Execute(w, v)
}

func initial(name, email string) string {
	for _, s := range []string{name, email} {
		if r, _ := utf8.DecodeRuneInString(strings.TrimSpace(s)); r != utf8.RuneError && unicode.IsLetter(r) {
			return string(unicode.ToUpper(r))
		}
	}
	return "?"
}

// shortSub shows enough of the identifier to be recognizable, which is the
// honest way to show "a permanent identifier" without a wall of hex.
func shortSub(sub string) string {
	if len(sub) <= 13 {
		return sub
	}
	return sub[:8] + "…" + sub[len(sub)-4:]
}

func decodeNonceHash(s string) ([]byte, error) {
	b, err := base64.RawURLEncoding.DecodeString(s)
	if err != nil || len(b) != 32 {
		return nil, errors.New("bad nonce hash")
	}
	return b, nil
}
