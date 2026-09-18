## 1. Choosing the key

- [x] 1.1 Split the choice from the refusal in `cli/src/freepod/keys.py`: `select_local_key` returns the key this machine offers or `None`, and `resolve_local_key` keeps raising for callers that need one, and verify the existing recovery tests pass unchanged
- [x] 1.2 Check the record's two halves in one place (`_recorded_key`): the file still hashes to the recorded fingerprint, and the account still lists it
- [x] 1.3 Adopt the client's generated key when it is among several matches (design D1), and verify a test asserting a generated/user-key tie resolves to the generated one and is recorded
- [x] 1.4 Keep the refusal for a tie among the user's own keys, and verify the existing `test_recovery_asks_when_several_match` still names both paths

## 2. Registering a key the account already holds

- [x] 2.1 Add `DuplicateKey` to the error hierarchy in `cli/src/freepod/__init__.py` and raise it from `_refusal` on 409 with `code: duplicate_key` (design D2)
- [x] 2.2 Have `key add <path>` record the key and report success on a duplicate, and verify a test asserting exit 0, the bound record, and the platform's own message on stderr
- [x] 2.3 Confirm other platform refusals still end the run, and verify the refusal test covers a non-duplicate code

## 3. What `key list` claims

- [x] 3.1 Mark `*` from `select_local_key` so the listing agrees with the SSH commands (design D3), and verify a test asserting a record whose file is gone is not marked
- [x] 3.2 Confirm a valid record is still marked exactly once, and verify the existing marking test passes unchanged

## 4. Documentation and release

- [x] 4.1 Update `cli/DEVELOPMENT.md` § Recovery for the preference, the rebind, and the `select_local_key`/`resolve_local_key` split
- [x] 4.2 Bump `__version__` to 0.14.0, and confirm `cli/uv.lock` needs no change — the client's version is dynamic and is not pinned there, so `uv run --frozen` in CI still resolves
- [x] 4.3 Run the client suite
