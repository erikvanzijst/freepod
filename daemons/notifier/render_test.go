package main

import (
	"strings"
	"testing"
)

func mustRender(t *testing.T, m message) (string, string) {
	t.Helper()
	text, html, err := render(m)
	if err != nil {
		t.Fatal(err)
	}
	return text, html
}

func full() message {
	return message{
		Subject:     "You have been given access to cloud.freepod.app",
		Heading:     "You have been given access",
		Body:        "you\\@example\\.com gave you access to their app.\n\nSign in with this address.",
		ActionLabel: "Open the app",
		ActionURL:   "https://cloud.freepod.app",
		Reason:      "You received this email because you@example.com added this address.",
	}
}

func TestFullNotificationInOrder(t *testing.T) {
	text, html := mustRender(t, full())
	order := []string{
		">You have been given access</h1>",
		"you@example.com gave you access to their app.</p>",
		`href="https://cloud.freepod.app" target="_blank"`,
		">Open the app</a>",
		"free of ads, tracking and lock-in.",
		"You received this email because",
	}
	at := 0
	for _, want := range order {
		i := strings.Index(html[at:], want)
		if i < 0 {
			t.Fatalf("HTML lacks %q after offset %d:\n%s", want, at, html)
		}
		at += i
	}
	wantText := "You have been given access\n\n" +
		"you@example.com gave you access to their app.\n\nSign in with this address.\n\n" +
		"Open the app: https://cloud.freepod.app\n\n" +
		"-- \nYou received this email because you@example.com added this address.\n"
	if text != wantText {
		t.Fatalf("text part:\n%q\nwant:\n%q", text, wantText)
	}
}

func TestNoActionNoButton(t *testing.T) {
	m := full()
	m.ActionLabel, m.ActionURL = "", ""
	text, html := mustRender(t, m)
	if strings.Contains(html, "border-radius:999px") || strings.Contains(html, "copy and paste") {
		t.Fatalf("button rendered without an action:\n%s", html)
	}
	if strings.Contains(text, "Open the app") {
		t.Fatalf("text part names an action: %q", text)
	}
}

func TestLayoutCommentsStayOutOfTheMail(t *testing.T) {
	_, html := mustRender(t, full())
	if strings.Contains(html, "<!--") || strings.Contains(html, "Keycloak") {
		t.Fatalf("layout comment in the rendered mail:\n%s", html)
	}
}

func TestHeadingFallsBackToSubject(t *testing.T) {
	m := full()
	m.Heading = ""
	_, html := mustRender(t, m)
	if !strings.Contains(html, ">You have been given access to cloud.freepod.app</h1>") {
		t.Fatalf("subject not used as heading:\n%s", html)
	}
}

func TestLinkInBody(t *testing.T) {
	m := full()
	m.Body = "Open [the app](https://cloud.freepod.app) now."
	text, html := mustRender(t, m)
	if !strings.Contains(html, `<a href="https://cloud.freepod.app" style="color:#2563EB;">the app</a>`) {
		t.Fatalf("link missing or unstyled:\n%s", html)
	}
	if !strings.Contains(text, "Open the app (https://cloud.freepod.app) now.") {
		t.Fatalf("text part: %q", text)
	}
}

func TestRawHTMLIsOmitted(t *testing.T) {
	for _, body := range []string{
		"<img src=x onerror=alert(1)>",
		"Hello <img src=x onerror=alert(1)> there",
		"<script>alert(1)</script>",
	} {
		m := full()
		m.Body = body
		text, html := mustRender(t, m)
		for _, bad := range []string{"<img", "onerror", "<script"} {
			if strings.Contains(html, bad) {
				t.Errorf("body %q: HTML contains %q:\n%s", body, bad, html)
			}
			if strings.Contains(text, bad) {
				t.Errorf("body %q: text contains %q: %q", body, bad, text)
			}
		}
	}
}

func TestDisallowedSchemesAreUnlinked(t *testing.T) {
	for _, body := range []string{
		"[click](javascript:alert(1))",
		"[click](JavaScript:alert(1))",
		"[click](data:text/html,hi)",
		"[click](ftp://example.com/x)",
		"<javascript:alert(1)>",
		"![pic](javascript:alert(1))",
	} {
		m := full()
		m.Body = body
		_, html := mustRender(t, m)
		lower := strings.ToLower(html)
		for _, bad := range []string{`href="javascript`, `href="data:`, `href="ftp:`, "<img"} {
			if strings.Contains(lower, bad) {
				t.Errorf("body %q rendered %s:\n%s", body, bad, html)
			}
		}
		if strings.HasPrefix(body, "[click]") && !strings.Contains(html, ">click</p>") {
			t.Errorf("body %q lost its link text:\n%s", body, html)
		}
	}
}

func TestAllowedSchemesStayLinks(t *testing.T) {
	m := full()
	m.Body = "[mail](mailto:support@freepod.eu), <https://freepod.eu> and [plain](http://example.com)"
	_, html := mustRender(t, m)
	for _, want := range []string{`href="mailto:support@freepod.eu"`, `href="https://freepod.eu"`, `href="http://example.com"`} {
		if !strings.Contains(html, want) {
			t.Errorf("missing %s:\n%s", want, html)
		}
	}
}

func TestPlainFieldsAreText(t *testing.T) {
	m := full()
	m.Heading = "<b>Hi</b>"
	m.ActionLabel = "<i>Go</i>"
	m.Reason = "Because <script>x</script>"
	_, html := mustRender(t, m)
	for _, want := range []string{"&lt;b&gt;Hi&lt;/b&gt;", "&lt;i&gt;Go&lt;/i&gt;", "Because &lt;script&gt;x&lt;/script&gt;"} {
		if !strings.Contains(html, want) {
			t.Errorf("missing escaped %s:\n%s", want, html)
		}
	}
	if strings.Contains(html, "<b>Hi") || strings.Contains(html, "<script>") {
		t.Fatalf("plain field rendered as markup:\n%s", html)
	}
}

func TestEscapedValuesReadAsWritten(t *testing.T) {
	m := full()
	m.Body = "\\*not emphasis\\* and \\[not a link\\]\\(https://x\\.example\\) by ana\\_b\\@example\\.com"
	text, html := mustRender(t, m)
	if strings.Contains(html, "<em>") || strings.Contains(html, "<a href=\"https://x") {
		t.Fatalf("escaped markup took effect:\n%s", html)
	}
	if !strings.Contains(text, "*not emphasis* and [not a link](https://x.example) by ana_b@example.com") {
		t.Fatalf("text part keeps escapes: %q", text)
	}
}

func TestOrdinaryMarkdown(t *testing.T) {
	m := full()
	m.Body = "Intro with **bold** and `code`.\n\n- one\n- two\n\n1. first\n2. second\n\n> quoted"
	text, html := mustRender(t, m)
	for _, want := range []string{
		"<strong>bold</strong>",
		`<code style="font-family:Menlo,Consolas,monospace; font-size:14px;">code</code>`,
		`<ul style="margin:0 0 16px 0; padding-left:24px;">`,
		"<li>one</li>",
		"<ol",
		`<blockquote style=`,
	} {
		if !strings.Contains(html, want) {
			t.Errorf("missing %s:\n%s", want, html)
		}
	}
	for _, want := range []string{"Intro with bold and code.", "- one\n- two", "1. first\n2. second", "> quoted"} {
		if !strings.Contains(text, want) {
			t.Errorf("text part lacks %q: %q", want, text)
		}
	}
}
