"""Fixed-repository GitHub inbox and recoverable outbox. No agent execution."""

from __future__ import annotations

import json
import re
import urllib.request

from .store import Principal, digest

REPOSITORY = "jsp1440/orchid-calyx-backend"
HUB = 1823
PREFIX = "[OC-ACS-v1]"


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    return json.loads(
        text,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")),
    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("GITHUB_REDIRECT_REFUSED")


class GitHub:
    def __init__(self, token, *, reporter_ids):
        if (
            not token
            or not reporter_ids
            or any(type(i) is not int or i < 1 for i in reporter_ids)
        ):
            raise ValueError("GITHUB_IDENTITY_CONFIG_REQUIRED")
        self.token = token
        self.reporter_ids = frozenset(reporter_ids)
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method, path, body=None):
        if not path.startswith(f"/repos/{REPOSITORY}/issues/{HUB}/comments"):
            raise PermissionError("GITHUB_PATH_REFUSED")
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            "https://api.github.com" + path,
            data=data,
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "OC-ACS-v1",
            },
        )
        with self.opener.open(req, timeout=20) as response:
            payload = response.read(4 * 1024 * 1024 + 1)
        if len(payload) > 4 * 1024 * 1024:
            raise ValueError("GITHUB_RESPONSE_TOO_LARGE")
        return strict_json(payload)

    def comments(self):
        comments = []
        for page in range(1, 101):
            batch = self.request(
                "GET",
                f"/repos/{REPOSITORY}/issues/{HUB}/comments?per_page=100&page={page}",
            )
            if not isinstance(batch, list):
                raise TypeError("GITHUB_RESPONSE_INVALID")
            comments.extend(batch)
            if len(batch) < 100:
                return comments
        # Never silently omit later comments when reconciling ambiguous delivery.
        raise ValueError("GITHUB_COMMENT_LIMIT_REACHED")

    def post(self, body):
        return self.request(
            "POST", f"/repos/{REPOSITORY}/issues/{HUB}/comments", {"body": body}
        )


class Bridge:
    def __init__(self, store, github, principals):
        if not principals or any(type(i) is not int or i < 1 for i in principals):
            raise ValueError("GITHUB_PRINCIPAL_CONFIG_REQUIRED")
        for principal in principals.values():
            if not isinstance(principal, Principal):
                raise TypeError("GITHUB_PRINCIPAL_INVALID")
            principal.key()
        self.store = store
        self.github = github
        self.principals = principals

    def ingest(self, comment):
        if not isinstance(comment, dict) or type(comment.get("id")) is not int:
            return "rejected"
        key = str(comment["id"])
        fingerprint = digest(
            {"body": comment.get("body"), "author": comment.get("user", {}).get("id")}
        )
        with self.store.transaction() as conn:
            old = self.store.sql(
                conn, "SELECT * FROM acs_inbox WHERE id=?", (key,)
            ).fetchone()
            if old:
                return "ignored" if old["fingerprint"] == fingerprint else "rejected"
            status = self._ingest(comment)
            self.store.sql(
                conn,
                "INSERT INTO acs_inbox (id,fingerprint,status) VALUES (?,?,?)",
                (key, fingerprint, status),
            )
            return status

    def _ingest(self, comment):
        body = comment.get("body", "")
        if not isinstance(body, str) or not body.startswith(PREFIX):
            return "ignored"
        if len(body.encode()) > 16384:
            return "rejected"
        principal = self.principals.get(comment.get("user", {}).get("id"))
        if principal is None:
            return "rejected"
        match = re.fullmatch(
            r"\[OC-ACS-v1\]\s*```json\s*\n(.*?)\n```\s*", body, re.DOTALL
        )
        if not match:
            return "rejected"
        try:
            event = strict_json(match.group(1))
            # Comments may be public. GitHub identity + attempt fence replaces secret token.
            if isinstance(event, dict) and "lease_token" in event:
                return "rejected"
            self.store.apply(event, principal)
        except (ValueError, TypeError, PermissionError, KeyError):
            return "rejected"
        return "accepted"

    def cycle(self):
        counts = {
            "accepted": 0,
            "rejected": 0,
            "ignored": 0,
            "reported": 0,
            "report_failed": 0,
        }
        comments = self.github.comments()
        for comment in comments:
            counts[self.ingest(comment)] += 1
        self.store.tick()
        # Snapshot count bounds a cycle even while new reports are arriving.
        for _ in range(len(self.store.reports())):
            report = self.store.take_report()
            if report is None:
                break
            marker = f"<!-- OC-ACS:{report['id']} -->"
            try:
                # Refresh before each write: handles prior POST whose response was lost.
                present = any(
                    c.get("body", "").startswith(marker + "\n")
                    and c.get("user", {}).get("id") in self.github.reporter_ids
                    and c.get("body") == report["body"]
                    for c in self.github.comments()
                )
                if not present and report["reconcile_only"]:
                    raise ValueError("FINAL_DELIVERY_UNCONFIRMED")
                if not present:
                    self.github.post(report["body"])
                self.store.settle_report(report["id"], report["token"], True)
                counts["reported"] += 1
            except (OSError, ValueError):
                self.store.settle_report(report["id"], report["token"], False)
                counts["report_failed"] += 1
        return counts
