package main

import "strings"

// invitationAcceptedKind is the notification kind queued to an owner when
// someone on the access list first signs in with their entry, accepting the
// invitation (access-first-sign-in-notice).
const invitationAcceptedKind = "access.invitation_accepted"

// notice is a notification as the outbox holds it. Body is Markdown; the other
// fields are plain text.
type notice struct {
	Subject, Heading, Body, ActionLabel, ActionURL, Reason string
}

// invitationAcceptedNotice tells an owner that email, on the list of the
// deployment at hostname, has signed in to it for the first time. It carries no text the
// owner or the person wrote.
func invitationAcceptedNotice(email, hostname string) notice {
	return notice{
		Subject: email + " accepted your invitation to " + hostname,
		Heading: "Your invitation was accepted",
		Body: mdEscape(email) + ", whom you gave access to " + mdEscape(hostname) +
			", signed in to it for the first time. If the app creates accounts when people first sign in, " +
			"it now knows them, so you can share with them or give them a role there.",
		ActionLabel: "Open the app",
		ActionURL:   "https://" + hostname,
		Reason:      "You received this email because you own " + hostname + " on Freepod and gave " + email + " access to it.",
	}
}

// mdEscape makes s literal Markdown by backslash-escaping every ASCII
// punctuation character, which CommonMark allows before any of them. The
// API's notifications.md follows the same rule.
func mdEscape(s string) string {
	var b strings.Builder
	for _, r := range s {
		if r < 0x80 && strings.ContainsRune("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~", r) {
			b.WriteByte('\\')
		}
		b.WriteRune(r)
	}
	return b.String()
}
