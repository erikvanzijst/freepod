package main

import "testing"

func TestMdEscapeMakesPunctuationLiteral(t *testing.T) {
	for in, want := range map[string]string{
		"ana_b@example.com":    `ana\_b\@example\.com`,
		"cloud-x.freepod.app":  `cloud\-x\.freepod\.app`,
		"[x](javascript:a)":    `\[x\]\(javascript\:a\)`,
		"*a* <b> `c` \\ ~d~ #": "\\*a\\* \\<b\\> \\`c\\` \\\\ \\~d\\~ \\#",
		"Zoë":                  "Zoë",
	} {
		if got := mdEscape(in); got != want {
			t.Errorf("mdEscape(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestInvitationAcceptedNotice(t *testing.T) {
	n := invitationAcceptedNotice("ana_b@example.com", "cloud-yourname.freepod.app")
	want := notice{
		Subject: "ana_b@example.com accepted your invitation to cloud-yourname.freepod.app",
		Heading: "Your invitation was accepted",
		Body: `ana\_b\@example\.com, whom you gave access to cloud\-yourname\.freepod\.app, ` +
			"signed in to it for the first time. If the app creates accounts when people first sign in, " +
			"it now knows them, so you can share with them or give them a role there.",
		ActionLabel: "Open the app",
		ActionURL:   "https://cloud-yourname.freepod.app",
		Reason:      "You received this email because you own cloud-yourname.freepod.app on Freepod and gave ana_b@example.com access to it.",
	}
	if n != want {
		t.Fatalf("notice\n got %+v\nwant %+v", n, want)
	}
}
