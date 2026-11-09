package main

import (
	"bytes"
	"embed"
	"html/template"
	"net/url"
	"strconv"
	"strings"

	"github.com/yuin/goldmark"
	"github.com/yuin/goldmark/ast"
	"github.com/yuin/goldmark/text"
	"github.com/yuin/goldmark/util"
)

// message is what a notification says, as its producer queued it. Only Body
// is Markdown; everything else is plain text.
type message struct {
	Subject     string
	Heading     string
	Body        string
	ActionLabel string
	ActionURL   string
	Reason      string
}

//go:embed layout.html
var layoutFS embed.FS

var layout = template.Must(template.ParseFS(layoutFS, "layout.html"))

// CommonMark with no extensions: no autolinking of bare URLs, and without
// WithUnsafe raw HTML is omitted from the output.
var markdown = goldmark.New()

var allowedSchemes = map[string]bool{"https": true, "http": true, "mailto": true}

// Mail clients drop <style> blocks, so the layout's look is set on each element.
var inlineStyles = map[ast.NodeKind]string{
	ast.KindParagraph:  "margin:0 0 16px 0;",
	ast.KindLink:       "color:#2563EB;",
	ast.KindAutoLink:   "color:#2563EB;",
	ast.KindList:       "margin:0 0 16px 0; padding-left:24px;",
	ast.KindHeading:    "margin:0 0 12px 0; font-size:18px; color:#0B1020;",
	ast.KindBlockquote: "margin:0 0 16px 0; padding-left:12px; border-left:3px solid #E2E6EE; color:#6B7488;",
	ast.KindCodeSpan:   "font-family:Menlo,Consolas,monospace; font-size:14px;",
}

// render returns the message as (plain text, HTML), each from the same parse
// of the body.
func render(m message) (string, string, error) {
	source := []byte(m.Body)
	doc := markdown.Parser().Parse(text.NewReader(source))
	sanitize(doc, source)

	var body bytes.Buffer
	if err := markdown.Renderer().Render(&body, source, doc); err != nil {
		return "", "", err
	}
	heading := m.Heading
	if heading == "" {
		heading = m.Subject
	}
	var html bytes.Buffer
	err := layout.Execute(&html, map[string]any{
		"Heading":     heading,
		"Body":        template.HTML(body.String()),
		"ActionLabel": m.ActionLabel,
		"ActionURL":   m.ActionURL,
		"Reason":      m.Reason,
	})
	if err != nil {
		return "", "", err
	}
	return plainText(heading, plainBody(doc, source), m), html.String(), nil
}

// sanitize unwraps links and drops images whose scheme is not allowed, keeping
// a link's text, and sets the inline styles. goldmark already blanks a few
// dangerous schemes; this narrows that to an allowlist.
func sanitize(doc ast.Node, source []byte) {
	var unwrap, drop []ast.Node
	_ = ast.Walk(doc, func(n ast.Node, entering bool) (ast.WalkStatus, error) {
		if !entering {
			return ast.WalkContinue, nil
		}
		switch v := n.(type) {
		case *ast.Link:
			if !allowedURL(string(v.Destination)) {
				unwrap = append(unwrap, n)
				return ast.WalkContinue, nil
			}
		case *ast.Image:
			if !allowedURL(string(v.Destination)) {
				drop = append(drop, n)
				return ast.WalkSkipChildren, nil
			}
		case *ast.AutoLink:
			if v.AutoLinkType == ast.AutoLinkURL && !allowedURL(string(v.URL(source))) {
				unwrap = append(unwrap, n)
				return ast.WalkContinue, nil
			}
		}
		if style, ok := inlineStyles[n.Kind()]; ok {
			n.SetAttributeString("style", []byte(style))
		}
		return ast.WalkContinue, nil
	})
	for _, n := range drop {
		n.Parent().RemoveChild(n.Parent(), n)
	}
	for _, n := range unwrap {
		parent := n.Parent()
		if a, ok := n.(*ast.AutoLink); ok {
			parent.InsertBefore(parent, n, ast.NewString(a.Label(source)))
		}
		for c := n.FirstChild(); c != nil; c = n.FirstChild() {
			parent.InsertBefore(parent, n, c)
		}
		parent.RemoveChild(parent, n)
	}
}

func allowedURL(raw string) bool {
	u, err := url.Parse(strings.TrimSpace(raw))
	return err == nil && allowedSchemes[strings.ToLower(u.Scheme)]
}

// plainBody renders the parsed body as text: escapes resolved, markup gone,
// a link as "text (url)".
func plainBody(doc ast.Node, source []byte) string {
	var blocks []string
	for c := doc.FirstChild(); c != nil; c = c.NextSibling() {
		if s := strings.TrimRight(plainBlock(c, source, ""), "\n"); s != "" {
			blocks = append(blocks, s)
		}
	}
	return strings.Join(blocks, "\n\n")
}

func plainBlock(n ast.Node, source []byte, indent string) string {
	switch v := n.(type) {
	case *ast.List:
		var b strings.Builder
		i := v.Start
		for item := n.FirstChild(); item != nil; item = item.NextSibling() {
			marker := "- "
			if v.IsOrdered() {
				marker = strconv.Itoa(i) + ". "
				i++
			}
			var parts []string
			for c := item.FirstChild(); c != nil; c = c.NextSibling() {
				parts = append(parts, strings.TrimRight(plainBlock(c, source, indent+"  "), "\n"))
			}
			b.WriteString(indent + marker + strings.Join(parts, "\n"+indent+"  ") + "\n")
		}
		return b.String()
	case *ast.Blockquote:
		var lines []string
		for c := n.FirstChild(); c != nil; c = c.NextSibling() {
			for _, l := range strings.Split(strings.TrimRight(plainBlock(c, source, ""), "\n"), "\n") {
				lines = append(lines, "> "+l)
			}
		}
		return strings.Join(lines, "\n") + "\n"
	case *ast.FencedCodeBlock, *ast.CodeBlock:
		var b strings.Builder
		lines := n.Lines()
		for i := 0; i < lines.Len(); i++ {
			seg := lines.At(i)
			b.Write(seg.Value(source))
		}
		return b.String()
	case *ast.ThematicBreak:
		return "---\n"
	case *ast.HTMLBlock:
		return ""
	default:
		return plainInline(n, source) + "\n"
	}
}

func plainInline(n ast.Node, source []byte) string {
	var b strings.Builder
	for c := n.FirstChild(); c != nil; c = c.NextSibling() {
		switch v := c.(type) {
		case *ast.Text:
			value := v.Segment.Value(source)
			if !v.IsRaw() {
				value = util.UnescapePunctuations(value)
				value = util.ResolveNumericReferences(value)
				value = util.ResolveEntityNames(value)
			}
			b.Write(value)
			if v.HardLineBreak() {
				b.WriteString("\n")
			} else if v.SoftLineBreak() {
				b.WriteString(" ")
			}
		case *ast.String:
			b.Write(v.Value)
		case *ast.CodeSpan:
			b.WriteString(plainInline(c, source))
		case *ast.Link:
			label := plainInline(c, source)
			dest := string(v.Destination)
			if label == dest || label == strings.TrimPrefix(dest, "mailto:") {
				b.WriteString(label)
			} else {
				b.WriteString(label + " (" + dest + ")")
			}
		case *ast.AutoLink:
			b.Write(v.Label(source))
		case *ast.Image, *ast.RawHTML:
		default:
			b.WriteString(plainInline(c, source))
		}
	}
	return b.String()
}

func plainText(heading, body string, m message) string {
	parts := []string{heading}
	if body != "" {
		parts = append(parts, body)
	}
	if m.ActionURL != "" {
		parts = append(parts, m.ActionLabel+": "+m.ActionURL)
	}
	parts = append(parts, "-- \n"+m.Reason)
	return strings.Join(parts, "\n\n") + "\n"
}
