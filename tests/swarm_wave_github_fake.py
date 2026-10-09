"""In-memory GitHub for multi-wave Swarm simulations.

A superset of the ``GitHub`` call fixture in ``tests/test_oc_swarm_claim.py``:
the same ``call(args, payload)`` transport that ``oc_swarm_claim`` and
``oc_swarm_settlement`` accept, with general ``--add-label``/``--remove-label``
semantics, durable comments with ids/authors/timestamps/``issue_url``, and the
transport interface ``oc_swarm_lease_reconcile.reconcile`` expects. It also
exports the repository snapshot exactly as the controller workflow's "Build
repository snapshot" step assembles it.

Deterministic: comment ids and timestamps come from a monotonic counter and a
fixed epoch, never from the wall clock. Fixture only; never live evidence.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import pairwise

BOT_LOGIN = "github-actions[bot]"
EPOCH = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


class FakeGitHub:
    def __init__(self, issues: list[dict], *, repository: str = "owner/repo") -> None:
        self.repository = repository
        self.rows = {int(row["number"]): deepcopy(row) for row in issues}
        for row in self.rows.values():
            row["labels"] = [x if isinstance(x, str) else x["name"] for x in row["labels"]]
        self.comments: dict[int, list[dict]] = {number: [] for number in self.rows}
        self.comment_index: dict[int, tuple[int, dict]] = {}
        self.runs: dict[int, str] = {}
        self.edits: list[list[str]] = []
        self._next_comment_id = 5000
        self._ticks = 0

    # -- deterministic clock -------------------------------------------------
    def now(self) -> datetime:
        return EPOCH + timedelta(minutes=self._ticks)

    def advance(self, minutes: int = 1) -> datetime:
        self._ticks += minutes
        return self.now()

    # -- gh CLI shapes -------------------------------------------------------
    def _view(self, number: int) -> dict:
        row = self.rows[number]
        return {"number": number, "title": row["title"], "body": row.get("body") or "",
                "state": row["state"], "labels": [{"name": x} for x in row["labels"]]}

    def _comment_view(self, number: int, comment: dict) -> dict:
        return {**deepcopy(comment),
                "issue_url": f"https://api.github.com/repos/{self.repository}/issues/{number}"}

    def _post_comment(self, number: int, body: str) -> dict:
        self.advance()
        self._next_comment_id += 1
        comment = {"id": self._next_comment_id, "body": body,
                   "user": {"login": BOT_LOGIN}, "created_at": iso(self.now())}
        self.comments[number].append(comment)
        self.comment_index[comment["id"]] = (number, comment)
        return self._comment_view(number, comment)

    def __call__(self, args: list[str], payload: dict | None = None):
        if args[:2] == ["issue", "view"]:
            return self._view(int(args[2]))
        if args[:2] == ["issue", "edit"]:
            self.edits.append(list(args))
            number = int(args[2])
            remove, add = [], []
            for flag, value in pairwise(args):
                if flag == "--remove-label":
                    remove.append(value)
                elif flag == "--add-label":
                    add.append(value)
            self.edit_labels(number, remove=remove, add=add)
            return None
        if args[:3] == ["api", "--method", "POST"]:
            assert args[-2:] == ["--input", "-"], args
            path = args[3]
            number = int(path.split("/issues/")[1].split("/")[0])
            return self._post_comment(number, payload["body"])
        if args[:3] == ["api", "--method", "GET"]:
            if "/comments?" in args[3]:
                from urllib.parse import parse_qs

                path, query = args[3].split("?", 1)
                number = int(path.split("/issues/")[1].split("/")[0])
                params = parse_qs(query)
                size = int(params["per_page"][0])
                page = int(params["page"][0])
                rows = self.comments[number][(page - 1) * size:page * size]
                return [self._comment_view(number, row) for row in rows]
            comment_id = int(args[3].rsplit("/", 1)[1])
            number, comment = self.comment_index[comment_id]
            return self._comment_view(number, comment)
        raise AssertionError(f"unexpected gh call: {args}")

    # -- oc_swarm_lease_reconcile transport interface -------------------------
    def running_issues(self) -> list[dict]:
        return [{**self._view(n), "updatedAt": iso(self.now())}
                for n, row in sorted(self.rows.items())
                if row["state"] == "OPEN" and "oc-running" in row["labels"]]

    def pull_requests(self) -> list[dict]:
        return []

    def comments_for(self, number: int) -> list[dict]:
        return [deepcopy(c) for c in self.comments[number]]

    def labeled_at(self, number: int):  # timeline is not modelled; receipts decide
        return None

    def run_status(self, run_id: int) -> str:
        return self.runs.get(run_id, "missing")

    def issue(self, number: int) -> dict:
        return self._view(number)

    def edit_labels(self, number: int, *, remove: list[str], add: list[str]) -> None:
        self.advance()
        row = self.rows[number]
        row["labels"] = [x for x in row["labels"] if x not in set(remove)]
        for label in add:
            if label not in row["labels"]:
                row["labels"].append(label)
        row["updatedAt"] = iso(self.now())

    def comment(self, number: int, body: str) -> dict:
        return self._post_comment(number, body)

    # -- controller snapshot (workflow "Build repository snapshot") ----------
    def snapshot(self) -> dict:
        issues = []
        for number, row in sorted(self.rows.items()):
            issue = {"number": number, "title": row["title"], "body": row.get("body") or "",
                     "labels": [{"name": x} for x in row["labels"]],
                     "createdAt": row["createdAt"], "updatedAt": row.get("updatedAt", row["createdAt"]),
                     "state": row["state"]}
            if row["state"] == "OPEN" and "oc-blocked" in row["labels"]:
                issue["comments"] = [{"id": c["id"], "body": c["body"]} for c in self.comments[number]]
            issues.append(issue)
        return {"issues": issues, "pull_requests": [], "budget_fingerprints": {},
                "now": iso(self.now())}

    def labels(self, number: int) -> set[str]:
        return set(self.rows[number]["labels"])


class ReconcileTransport:
    """Adapter giving ``reconcile`` its ``comments(number)`` method name."""

    def __init__(self, fake: FakeGitHub) -> None:
        self._fake = fake
        self.repository = fake.repository

    def __getattr__(self, name):
        return getattr(self._fake, name)

    def comments(self, number: int) -> list[dict]:
        return self._fake.comments_for(number)
