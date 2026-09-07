#!/usr/bin/env python3
"""Set every Keycloak account's username to its email address, in one pass.

Written for the OpenSpec change `keycloak-drop-registration-username`, section
2. Once `registrationEmailAsUsername` is enabled on the realm, Keycloak
overwrites a divergent username with the email address on the *next* update to
that account — whenever that happens to be, one account at a time, with nothing
connecting it to a configuration change. This pass does it deliberately
instead: one event, a known scope, and a record of what the usernames were.

Report-only is the default. Writing requires --apply, because renaming an
account's login name is not something to do by forgetting a flag.

A record of every divergent account — id, previous username, email — is written
before any account is touched, and in report-only mode too, so the list exists
before anything changes. Reverting the realm setting does not restore
usernames; this file is the only place the old values survive.

The pass is idempotent: an account whose username already equals its email is
skipped without a write. Keycloak may have converted an account on its own
between the Terraform apply and this run, and that outcome is identical to the
one this pass produces.

Writes go through the admin API rather than direct SQL, for the two reasons
seed-keycloak-users.py gives: Terraform does not manage end-user accounts
(`keycloak-terraform-config`), and Keycloak's Infinispan `users` cache makes
rows written straight to Postgres unreliable.

Usage:
    export KEYCLOAK_ADMIN_PASSWORD=...

    # 1. Look, and produce the record.
    scripts/normalize-keycloak-usernames.py --record var/usernames.json

    # 2. Convert one observability-group member and have them sign in to
    #    Freepod and to Grafana before going further.
    scripts/normalize-keycloak-usernames.py --record var/usernames.json \
        --only fred --apply

    # 3. Convert the rest.
    scripts/normalize-keycloak-usernames.py --record var/usernames.json --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

PAGE_SIZE = 100


class AdminApi:
    def __init__(self, url: str, realm: str, admin_user: str, admin_password: str):
        self.url = url.rstrip("/")
        self.realm = realm
        self._admin_user = admin_user
        self._admin_password = admin_password

    def _mint_token(self) -> str:
        """Admin access tokens live ~60s, so mint one per call rather than cache."""
        body = urllib.parse.urlencode(
            {
                "client_id": "admin-cli",
                "username": self._admin_user,
                "password": self._admin_password,
                "grant_type": "password",
            }
        ).encode()
        req = urllib.request.Request(
            f"{self.url}/realms/master/protocol/openid-connect/token", data=body
        )
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)["access_token"]

    def request(self, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": f"Bearer {self._mint_token()}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"{self.url}/admin/realms/{self.realm}{path}",
            data=data,
            method=method,
            headers=headers,
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()

    def all_users(self) -> list[dict]:
        users: list[dict] = []
        first = 0
        while True:
            q = urllib.parse.urlencode({"first": first, "max": PAGE_SIZE})
            _, payload = self.request("GET", f"/users?{q}")
            page = json.loads(payload)
            users.extend(page)
            if len(page) < PAGE_SIZE:
                return users
            first += PAGE_SIZE

    def get_user(self, user_id: str) -> dict:
        _, payload = self.request("GET", f"/users/{user_id}")
        return json.loads(payload)

    def set_username(self, user: dict, username: str) -> None:
        """PUT the whole representation back with one field changed.

        The admin API takes a full UserRepresentation on update, so send back
        what it just gave us rather than a one-key body that would drop
        whatever it does not mention.
        """
        self.request("PUT", f"/users/{user['id']}", {**user, "username": username})


def classify(users: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split accounts into divergent, already-matching, and unconvertible."""
    divergent, matching, no_email = [], [], []
    for u in users:
        email = u.get("email")
        if not email:
            no_email.append(u)
        elif u.get("username") == email.lower():
            matching.append(u)
        else:
            divergent.append(u)
    return divergent, matching, no_email


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--url", default="https://keycloak.freepod.eu", help="Keycloak base URL")
    p.add_argument("--realm", default="freepod", help="target realm (default: freepod)")
    p.add_argument("--admin-user", default="admin")
    p.add_argument(
        "--admin-password",
        default=os.environ.get("KEYCLOAK_ADMIN_PASSWORD"),
        help="defaults to $KEYCLOAK_ADMIN_PASSWORD",
    )
    p.add_argument(
        "--record",
        required=True,
        metavar="PATH",
        help="JSON file to write the id/previous username/email of every "
        "divergent account to, before anything is written",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="actually write. Without it the pass reports and changes nothing.",
    )
    p.add_argument(
        "--only",
        action="append",
        metavar="USERNAME",
        help="convert only these usernames (repeatable). Use this for the "
        "one-account gate before converting everybody.",
    )
    args = p.parse_args()

    if not args.admin_password:
        print(
            "error: no admin password (--admin-password or $KEYCLOAK_ADMIN_PASSWORD)",
            file=sys.stderr,
        )
        return 2

    api = AdminApi(args.url, args.realm, args.admin_user, args.admin_password)
    users = api.all_users()
    divergent, matching, no_email = classify(users)

    # Merge rather than replace. After a pass the divergent set is empty, so a
    # re-run against the same file would otherwise truncate away the only
    # surviving copy of the previous usernames.
    record = {}
    if os.path.exists(args.record):
        with open(args.record) as fh:
            record = {entry["id"]: entry for entry in json.load(fh)}
    for u in divergent:
        record.setdefault(
            u["id"],
            {"id": u["id"], "previousUsername": u.get("username"), "email": u["email"]},
        )
    with open(args.record, "w") as fh:
        json.dump([record[k] for k in sorted(record)], fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"realm {args.realm!r}: {len(users)} account(s)")
    print(f"  {len(matching)} already username == email")
    print(f"  {len(divergent)} divergent, recorded in {args.record}")
    for u in no_email:
        print(f"  warn: {u.get('username')!r} ({u['id']}) has no email; cannot convert")

    selected = divergent
    if args.only:
        wanted = set(args.only)
        selected = [u for u in divergent if u.get("username") in wanted]
        missing = wanted - {u.get("username") for u in selected}
        if missing:
            print(f"error: --only named no divergent account: {sorted(missing)}", file=sys.stderr)
            return 2

    if not selected:
        print("\nnothing to convert")
        return 0

    failures = 0
    print()
    for u in selected:
        target = u["email"].lower()
        print(f"{u['username']!r} -> {target!r}  ({u['id']})")
        if not args.apply:
            print("    report-only; pass --apply to write")
            continue
        try:
            # Re-read: the account may have been converted by Keycloak itself
            # since the listing, which makes this a no-op rather than a write.
            current = api.get_user(u["id"])
            if current.get("username") == target:
                print("    skip: already converted")
                continue
            api.set_username(current, target)
            print("    converted")
        except urllib.error.HTTPError as e:
            print(f"    FAILED {e.code}: {e.read().decode()[:300]}")
            failures += 1

    print()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
