# Release & PR Digest → Slack (GitHub Action)

Posts a short, categorized digest of merged PRs to Slack, either **weekly** or **per release**.

- Deterministic template, **no LLM**: titles, authors, labels, and links come straight from GitHub.
- Composite action plus one stdlib Python script. No Docker, no `pip install`.
- **Safe by default:** it posts only when you pass a Slack webhook. Otherwise it just prints the digest to the log and the job summary.

## Quick start

1. In Slack, create an [Incoming Webhook](https://api.slack.com/messaging/webhooks) for a private test channel.
2. In your repo, add it as a secret: **Settings → Secrets and variables → Actions → `SLACK_WEBHOOK_URL`**.
3. Add `.github/workflows/weekly-digest.yml`:

```yaml
name: Weekly PR digest
on:
  schedule:
    - cron: "0 13 * * 1"   # Mondays 13:00 UTC
  workflow_dispatch:
permissions:
  contents: read
  pull-requests: read
jobs:
  digest:
    runs-on: ubuntu-latest
    steps:
      - uses: saasops05/release-digest-action@v1
        with:
          slack-webhook-url: ${{ secrets.SLACK_WEBHOOK_URL }}
```

A fuller version that also runs on `release: published` and has a dry-run toggle is in [`example-workflow.yml`](./example-workflow.yml).

**Try it with no secrets at all:**

```yaml
      - uses: saasops05/release-digest-action@v1
        with:
          fixture: sample   # bundled sample data, no GitHub API calls, nothing posted
```

## Inputs

| Input | Default | Notes |
|---|---|---|
| `slack-webhook-url` | `""` | Pass from a secret. Empty means print only, never post. |
| `mode` | `weekly` | `weekly` = PRs merged in the last `days`. `release` = PRs referenced (`#123`) in the release notes. |
| `days` | `7` | Look-back window for `weekly`. |
| `release-tag` | `""` | For `release` mode. Empty = the tag from the release event, otherwise the latest release. |
| `repo` | current repo | `owner/name`. |
| `github-token` | `github.token` | Needs `contents: read` and `pull-requests: read`. |
| `dry-run` | `false` | `true` = never post, even if a webhook is set. |
| `fixture` | `""` | `sample` or the path to a fixture JSON. Runs offline. |
| `show-footer` | `true` | One-line attribution footer in the Slack message. Set `false` to remove it. |

**Outputs:** `pr-count`, `posted` (`true`/`false`), `digest-file` (path to the rendered text).

PRs are grouped by label: `feature`/`enhancement` → Features, `bug`/`fix` → Fixes, `chore`/`deps`/`ci`/`docs`/`refactor` → Maintenance, anything else → Other. Weekly mode lists up to 100 PRs and says "showing N of M" if there are more. If the GitHub API call fails, the step fails and nothing is posted. It never makes up a summary.

## Sample output

Rendered from the bundled fixture (`fixture-weekly.json`, fictional data). Slack shows the `<url|text>` links as clickable text:

```
:package: *Weekly PR digest*
_Period:_ 2026-09-21 → 2026-09-28 (7 days)  |  _Repo:_ `example-org/example-app`
<https://github.com/example-org/example-app/pulls|View on GitHub>
:test_tube: _Sample data from a fixture file — not a real repo._

:sparkles: *Features*
• <https://github.com/example-org/example-app/pull/412|#412 Add cohort retention chart to dashboards> — `@maya-chen` · _feature, frontend_
• <https://github.com/example-org/example-app/pull/405|#405 Introduce workspace-level API rate limit headers> — `@samir-patel` · _feature, api_
• <https://github.com/example-org/example-app/pull/389|#389 Ship CSV export for custom metric boards> — `@maya-chen` · _feature, export_

:bug: *Fixes*
• <https://github.com/example-org/example-app/pull/408|#408 Fix timezone drift in scheduled report exports> — `@jordan-lee` · _bug, backend_
• <https://github.com/example-org/example-app/pull/397|#397 Prevent duplicate webhook deliveries on retry> — `@jordan-lee` · _bug, reliability_

:wrench: *Maintenance*
• <https://github.com/example-org/example-app/pull/401|#401 Bump pytest and ruff; quiet CI flaky warnings> — `@devin-ross` · _chore, ci_
• <https://github.com/example-org/example-app/pull/393|#393 Document SSO mapping for Okta enterprise tenants> — `@aisha-nguyen` · _docs, chore_

_7 merged PR(s) · template-generated, no LLM._

Built by SaaS Ops Tune-Up — want this wired to your stack? Free AI Ops Scorecard: <https://saasops05.github.io/saasops-digest-demo/scorecard.html|saasops05.github.io/saasops-digest-demo/scorecard.html>
```

Also in [`sample-output.txt`](./sample-output.txt).

## Run locally

Requires Python 3.8+. No dependencies.

```bash
python3 digest.py --fixture sample                  # offline, prints only
python3 digest.py --fixture fixture-release.json
python3 digest.py --fixture fixture-empty.json      # empty-window message
python3 digest.py --repo owner/name --days 7 --dry-run   # live GitHub read, no post
python3 -m unittest -v test_digest.py               # offline tests (uses a local mock webhook)
```

Environment variables are listed in [`.env.example`](./.env.example). Keep secrets in env vars or Action secrets, never in files you commit.

## Files

```
action.yml            composite action definition
digest.py             fetch + render + post (stdlib only)
fixture-*.json        offline sample data (fictional)
example-workflow.yml  copy into .github/workflows/
test_digest.py        offline tests
sample-output.txt     rendered sample
.env.example          local env vars
```

## License

MIT. See [LICENSE](./LICENSE).

---

<sub>Built by SaaS Ops Tune-Up. Want this wired to your stack? Free AI Ops Scorecard: https://saasops05.github.io/saasops-digest-demo/scorecard.html</sub>
