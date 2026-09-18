## Context

The client must name exactly one key before it connects: the edge answers every
offered key with "partial success", so a client that offers several exhausts
`MaxAuthTries` and is refused before reaching the right one. That constraint is
why `resolve_local_key` exists and why `edge_options` pins `IdentitiesOnly=yes`
with a single `-i`. It says nothing about which key to name when more than one
would do — which is the question this change answers.

## Decisions

### D1: The generated key wins a tie; the user's keys still ask

Every key registered on the account authenticates equally, because the edge
resolves a connection against the account rather than against one key
(`ssh-auth/resolve.go`). So a tie is not a question about *access*; it is a
question about which key this machine should be bound to from now on, since
adoption is written to `keys.json`.

Where the client's own generated key is one of the candidates, that question
has an answer: it is the key this client created for this machine, it is
independently revocable, and it is not one the user curates for other hosts.
Preferring it is consistent with `candidate_public_keys()`, which already
orders client-owned keys first, deliberately.

A tie among the user's own keys keeps the original behavior. Nothing
distinguishes `~/.ssh/id_rsa.pub` from `~/.ssh/work.pub` from here, and binding
a machine to the wrong one of those is a choice the user should make.

**Alternative rejected:** always adopt the first candidate. It would fix the
reported failure, but "first" is `sorted()` order over `~/.ssh`, which is not a
preference the user expressed and would read as arbitrary the first time it
picked wrong.

### D2: A duplicate is acted on, not reported

`freepod key add <path>` exists to answer "use *this* key on this machine", and
the registration is a means to that end. When the platform reports 409
`duplicate_key`, the state the command was asking for already holds, so the
client records the key and reports success rather than failing on a conflict
that is not one.

This is what makes the ambiguity message honest: the command it names now
works for a key the account already holds, which is every key it can list.

The client branches on the `code`, not on prose or on the bare status: 409 is
reserved for this condition on this endpoint, but `code` is the identifier the
API contract makes stable, and `api/app/api/util.py` already emits it.

**Alternative rejected:** have `key add` pre-check the listing it already
fetched and skip the POST. It reads the same in the common case but loses to a
race, and it would still need the 409 branch to be correct — two paths where
one will do.

### D3: `*` means "can be offered", not "was once recorded"

`key list` and the SSH commands consulted the record differently, so they could
disagree about the same machine. `select_local_key` is now the single answer to
"which key does this machine offer", and `resolve_local_key` is that plus the
error for when there is none.

The split exists because a listing must not fail: `select_local_key` returns
`None` where `resolve_local_key` raises. `key list` therefore reports what is
true without being able to refuse.

A consequence worth stating: a stale record now shows no `*` at all, where it
previously showed a confident one. That is the point — the previous mark was
wrong, and it was the signal that sent the reporting user looking in the wrong
place.

## Risks

- **A user who wanted their personal key bound gets the generated one
  instead.** Bounded: `freepod key add <path>` now rebinds, which is the
  documented way to state the preference, and the `*` in `key list` shows which
  key is bound.
- **A machine silently rebinds on `key add` where it previously errored.** That
  is the intended behavior, and the command already reported the fingerprint it
  bound; the message now says so explicitly.
