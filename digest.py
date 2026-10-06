#!/usr/bin/env python3
"""Release & PR digest -> Slack.

Deterministic template (no LLM), Python 3.8+ stdlib only.

Modes:
  weekly  - PRs merged in the last N days (default 7)
  release - PRs referenced (#123) in a release body; falls back to recent merges

Config comes from env vars (set by action.yml) or CLI flags (local use).
Posts to Slack ONLY when SLACK_WEBHOOK_URL is set and dry-run is off.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
SAMPLE_FIXTURE = HERE / "fixture-weekly.json"
API = "https://api.github.com"
FOOTER = (
    "Built by SaaS Ops Tune-Up \u2014 want this wired to your stack? "
    "Free AI Ops Scorecard: "
    "<https://saasops05.github.io/saasops-digest-demo/scorecard.html|"
    "saasops05.github.io/saasops-digest-demo/scorecard.html>"
)

CATEGORY_MAP = {
    "feature": "features", "enhancement": "features", "feat": "features",
    "bug": "fixes", "bugfix": "fixes", "fix": "fixes",
    "chore": "chores", "maintenance": "chores", "deps": "chores",
    "dependencies": "chores", "ci": "chores", "docs": "chores",
    "documentation": "chores", "refactor": "chores",
}
CATEGORY_ORDER = ("features", "fixes", "chores", "other")
HEADINGS = {
    "features": ":sparkles: *Features*",
    "fixes": ":bug: *Fixes*",
    "chores": ":wrench: *Maintenance*",
    "other": ":grey_question: *Other*",
}


# ---------------------------------------------------------------- helpers
def truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def esc(text: str) -> str:
    """Escape Slack mrkdwn control characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def categorize(labels: List[str]) -> str:
    for label in labels:
        cat = CATEGORY_MAP.get(label.strip().lower())
        if cat:
            return cat
    return "other"


def gh_get(path: str, token: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "release-digest-action",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(API + path, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def pr_from_api(item: Dict[str, Any]) -> Dict[str, Any]:
    merged = item.get("merged_at") or (item.get("pull_request") or {}).get("merged_at")
    return {
        "number": item.get("number"),
        "title": item.get("title") or "Untitled",
        "author": (item.get("user") or {}).get("login") or "unknown",
        "labels": [l.get("name", "") for l in item.get("labels") or []],
        "url": item.get("html_url") or "",
        "merged_at": merged,
    }


# ---------------------------------------------------------------- fetchers
def fetch_weekly(repo: str, token: str, days: int, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    since = (now - dt.timedelta(days=days)).date().isoformat()
    q = "repo:{} is:pr is:merged merged:>={}".format(repo, since)
    data = gh_get("/search/issues?" + urllib.parse.urlencode(
        {"q": q, "sort": "updated", "order": "desc", "per_page": 100}), token)
    prs = [pr_from_api(i) for i in data.get("items") or []]
    total = int(data.get("total_count") or len(prs))
    return {
        "title": "Weekly PR digest",
        "repo": repo,
        "period": "{} \u2192 {} ({} days)".format(since, now.date().isoformat(), days),
        "url": "https://github.com/{}/pulls?q={}".format(
            repo, urllib.parse.quote("is:pr is:merged merged:>=" + since)),
        "total_count": total,
        "pull_requests": prs,
    }


def event_release_tag() -> str:
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            return ((json.load(fh).get("release") or {}).get("tag_name")) or ""
    except (OSError, ValueError):
        return ""


def fetch_release(repo: str, token: str, tag: str) -> Dict[str, Any]:
    if tag:
        rel = gh_get("/repos/{}/releases/tags/{}".format(repo, urllib.parse.quote(tag)), token)
    else:
        rel = gh_get("/repos/{}/releases/latest".format(repo), token)
    tag = rel.get("tag_name") or "unknown"
    numbers: List[int] = []
    for m in re.finditer(r"(?:#|/pull/)(\d+)\b", rel.get("body") or ""):
        n = int(m.group(1))
        if n not in numbers:
            numbers.append(n)
    prs: List[Dict[str, Any]] = []
    for n in numbers[:50]:
        try:
            pr = gh_get("/repos/{}/pulls/{}".format(repo, n), token)
        except Exception:  # issue refs (#n that aren't PRs) 404 - skip them
            continue
        if pr.get("merged_at"):
            prs.append(pr_from_api(pr))
    published = (rel.get("published_at") or "")[:10]
    return {
        "title": "Release digest \u2014 " + (rel.get("name") or tag),
        "repo": repo,
        "period": tag + (" ({})".format(published) if published else ""),
        "url": rel.get("html_url") or "https://github.com/{}/releases".format(repo),
        "total_count": len(prs),
        "pull_requests": prs,
    }


def load_fixture(path: str) -> Dict[str, Any]:
    p = SAMPLE_FIXTURE if path.strip().lower() == "sample" else Path(path)
    if not p.is_absolute() and not p.exists():
        p = HERE / p
    with open(p, encoding="utf-8") as fh:
        data = json.load(fh)
    data["sample"] = True
    return data


# ---------------------------------------------------------------- render
def render(payload: Dict[str, Any], show_footer: bool = True) -> str:
    prs = payload.get("pull_requests") or []
    lines = [":package: *{}*".format(esc(payload.get("title") or "PR digest"))]
    meta = "_Period:_ {}  |  _Repo:_ `{}`".format(
        esc(payload.get("period") or "n/a"), esc(payload.get("repo") or "n/a"))
    lines.append(meta)
    if payload.get("url"):
        lines.append("<{}|View on GitHub>".format(payload["url"]))
    if payload.get("sample"):
        lines.append(":test_tube: _Sample data from a fixture file \u2014 not a real repo._")
    lines.append("")

    if not prs:
        lines.append(":information_source: No merged PRs in this window.")
    else:
        buckets: Dict[str, List[Dict[str, Any]]] = {c: [] for c in CATEGORY_ORDER}
        for pr in prs:
            buckets[categorize(list(pr.get("labels") or []))].append(pr)
        for cat in CATEGORY_ORDER:
            if not buckets[cat]:
                continue
            lines.append(HEADINGS[cat])
            for pr in buckets[cat]:
                label = "#{} {}".format(pr.get("number", "?"), esc((pr.get("title") or "Untitled").strip()))
                item = "<{}|{}>".format(pr["url"], label) if pr.get("url") else label
                labels = ", ".join(esc(l) for l in pr.get("labels") or []) or "no labels"
                lines.append("\u2022 {} \u2014 `@{}` \u00b7 _{}_".format(item, esc(pr.get("author") or "unknown"), labels))
            lines.append("")
        total = int(payload.get("total_count") or len(prs))
        count = "{} merged PR(s)".format(len(prs))
        if total > len(prs):
            count = "showing {} of {} merged PRs".format(len(prs), total)
        lines.append("_{} \u00b7 template-generated, no LLM._".format(count))

    if show_footer:
        lines.append("")
        lines.append(FOOTER)
    return "\n".join(lines).rstrip() + "\n"


def post_slack(webhook: str, text: str) -> None:
    req = urllib.request.Request(
        webhook, data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status >= 400:
            raise RuntimeError("Slack webhook returned HTTP {}".format(resp.status))


def gh_output(**kv: Any) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            for k, v in kv.items():
                fh.write("{}={}\n".format(k, v))


def step_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("### Release & PR digest\n\n```\n" + text + "```\n")


# ---------------------------------------------------------------- main
def parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    env = os.environ.get
    p = argparse.ArgumentParser(description="Release & PR digest -> Slack (no LLM).")
    p.add_argument("--mode", default=env("DIGEST_MODE") or "weekly", choices=["weekly", "release"])
    p.add_argument("--days", type=int, default=int(env("DIGEST_DAYS") or 7))
    p.add_argument("--repo", default=env("GITHUB_REPO") or env("GITHUB_REPOSITORY") or "")
    p.add_argument("--release-tag", default=env("RELEASE_TAG") or "")
    p.add_argument("--fixture", default=env("DIGEST_FIXTURE") or "",
                   help="Fixture JSON path, or 'sample'. Skips the GitHub API.")
    p.add_argument("--dry-run", action="store_true", default=truthy(env("DIGEST_DRY_RUN")),
                   help="Never post to Slack.")
    p.add_argument("--no-footer", action="store_true",
                   default=not truthy(env("DIGEST_SHOW_FOOTER") or "true"))
    p.add_argument("--out", default="", help="Write digest to this file too.")
    return p.parse_args(argv)


def resolve(args: argparse.Namespace) -> Tuple[Dict[str, Any], str]:
    if args.fixture:
        return load_fixture(args.fixture), "fixture " + args.fixture
    if not args.repo or args.repo.count("/") != 1:
        raise ValueError("repo must be owner/name (set --repo, GITHUB_REPO, or use --fixture sample)")
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if args.mode == "weekly":
        return fetch_weekly(args.repo, token, args.days), "GitHub API weekly {}".format(args.repo)
    tag = args.release_tag or event_release_tag()
    return fetch_release(args.repo, token, tag), "GitHub API release {} {}".format(args.repo, tag or "latest")


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        payload, source = resolve(args)
    except Exception as exc:  # no invented summary on failure
        print("::error::Digest failed: {}".format(exc), file=sys.stderr)
        gh_output(**{"pr-count": 0, "posted": "false", "digest-file": ""})
        return 1

    text = render(payload, show_footer=not args.no_footer)
    print("# source: " + source, file=sys.stderr)
    sys.stdout.write(text)

    out = args.out or (os.path.join(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir(), "release-digest.txt")
                       if os.environ.get("GITHUB_ACTIONS") else "")
    if out:
        Path(out).write_text(text, encoding="utf-8")
    step_summary(text)

    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    posted = False
    if args.dry_run:
        print("[slack] dry-run: not posted.", file=sys.stderr)
    elif not webhook:
        print("[slack] no SLACK_WEBHOOK_URL: printed only, not posted.", file=sys.stderr)
    else:
        try:
            post_slack(webhook, text)
            posted = True
            print("[slack] posted.", file=sys.stderr)
        except Exception as exc:
            print("::error::Slack post failed: {}".format(exc), file=sys.stderr)
            gh_output(**{"pr-count": len(payload.get("pull_requests") or []), "posted": "false", "digest-file": out})
            return 2

    gh_output(**{"pr-count": len(payload.get("pull_requests") or []),
                 "posted": str(posted).lower(), "digest-file": out})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
