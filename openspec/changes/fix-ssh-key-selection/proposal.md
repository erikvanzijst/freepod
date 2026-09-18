## Why

A user who has run `freepod key add` once too often — an ordinary way to end
up with both a client-generated key and a personal one registered — is refused
by every SSH command:

```
error: several local keys are registered on this account; name the one to use
with `freepod key add <path>`:
  /home/erik/.config/freepod/id_ed25519.pub
  /home/erik/.ssh/id_rsa.pub
```

Three things are wrong with that.

**The remedy named in the error cannot work.** `freepod key add <path>` with a
path goes straight to `POST /ssh-keys`, and the platform refuses a key the
account already holds with **409 `duplicate_key`**. Both keys listed in the
message are by definition already registered, so following the instruction
produces `This key is already registered as 'The OG'` and the machine stays
unusable. There is no in-band way out: the user must hand-edit `keys.json` or
revoke a key they wanted to keep.

**The refusal is not protecting anything.** Authorization at the edge is per
account, not per key: `ssh-auth/resolve.go` joins `user_ssh_key` on
`k.user_id = d.user_id AND k.fingerprint = $2`, so any key registered on the
owning account admits the connection. Both candidates would have worked
identically. The guard exists because adoption is *persisted* and the client
should not silently bind a machine to a key the user curates for other hosts —
a real concern, but not one that applies when the client's own generated key is
among the candidates.

**`key list` and the SSH commands disagree.** `key list` marks `*` from the
record's fingerprint alone, while `resolve_local_key` also checks that the
recorded path still holds that key. A stale record therefore shows a confident
`*` next to a key that every connection then refuses to use — which is exactly
what the reporting user saw.

## What Changes

- Recovery **adopts the client's own generated key** when it is among several
  matching candidates, instead of refusing. A tie among the user's own keys is
  still theirs to settle, and is still reported.
- `freepod key add <path>` naming a key the account already holds **records it
  as this machine's key** and succeeds, rather than failing on the duplicate.
  This makes the ambiguity error's advice true for the case that remains.
- `key list` marks the key this machine can actually **offer** — a record whose
  file is gone or replaced is not marked, because no connection would use it.

No change to what is offered over the wire, to the record's format or location,
to its per-environment keying, or to how a key is registered in the first
place. `keys.json` written by an earlier client is read unchanged.

## Capabilities

### Modified Capabilities

- `cli-ssh-keys`: how recovery settles several matching candidates, what
  registering an already-registered key does, and what the `*` in `key list`
  claims.

## Impact

- `cli/src/freepod/keys.py` — `select_local_key` splits the choice from the
  refusal; `_refusal` gives a duplicate its own class.
- `cli/src/freepod/cli.py` — `key add` acts on the duplicate; `key list` marks
  what can be offered.
- `cli/src/freepod/__init__.py` — `DuplicateKey` joins the error hierarchy;
  version to 0.14.0.
- `cli/tests/test_keys.py` — coverage for the preference, the rebind, and the
  stale record.
- No platform change: the API, the edge and the `ssh-auth` resolver are
  untouched, and no version of the client becomes unsupported.
