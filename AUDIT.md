# FrontierWatch AI — Repository Audit (2026-10-18)

## Scope and baseline

Reviewed the tracked repository tree: monitoring workflow, CI, tracker, evidence utilities, tests, public snapshot, README, SETUP and ignore rules. Cross-checked GitHub Actions job history and actual unit-test logs. The scan is a **code/configuration and CI audit**, not a credential inspection or a confirmation that unknown models exist.

At audit start, the latest saved provider catalogs had OpenAI **127**, Anthropic **14**, Google **63**, OpenRouter **471** provider-list entries. The `_evidence` history was empty. These counts are not globally unique model counts. The latest successful monitor run before the fixes reported 24 tests, all passing.

## Resolved

| Severity | Finding | Mitigation |
| --- | --- | --- |
| High | Invalid, empty or sharply truncated catalog responses could replace good snapshots and later produce false mass-discovery alerts | Validate lists and identifiers, reject empty response or >50% decrease; preserve previous provider data |
| High | More than five new SDK commits could cause uninspected patches to be lost when the main commit pointer advanced | Separate `_sdk_patch_commits` from commit-message cursors; inspect older unseen commits first with two per-repository budget; retry failed patch requests |
| High | Telegram failure could abort state persistence or lose a change notification after advancing catalog pointers | Persistent `_pending_alerts` queue, bounded retries and nonfatal network errors; at-least-once delivery |
| High | Malformed/interrupted state writes could leave an incomplete local JSON file | Write temporary file first, then atomic replace |
| Medium | New SDK release source could generate a false retrospective alert | Preserve first-seen release baseline |
| Medium | No automatic unit-test workflow existed for code edits, leading to untested deployments | Added `.github/workflows/ci.yml` with push/PR unit tests and read-only permissions |
| Medium | Anthropic/Gemini pagination could prevent complete model lists from being recorded | Support `after_id` / `last_id` and Gemini `pageToken` / `nextPageToken`; reject incomplete, repeated or over-limit page chains |
| Medium | Missing health diagnostics made provider failures hard to distinguish from no changes | Add sanitized per-provider health, count and HTTP error categories to `_health` |
| Medium | Unauthenticated GitHub REST API was susceptible to frequent rate limits (typically 60 requests/hour) | Use the built-in GitHub Actions token **only for api.github.com**; no personal token required |
| Medium | Cron on quarter-hour boundaries can be delayed/dropped by the GitHub scheduler | Move to UTC minutes 07, 22, 37, 52; set workflow timeout |

**Unit-test verification:** [GitHub Actions CI run](https://github.com/Armaganakcann/frontierwatch-ai/actions/runs/39123230268) passed **45 tests** after the Python changes. Later workflow and documentation changes should be observed in a subsequent monitor run; they do not themselves verify real API or Telegram delivery.

## Remaining gaps and honest limitations

### Priority 0 — automatic schedule has not yet been verified

At inspection time, the repository had **zero** GitHub Actions runs with the `schedule` event; earlier monitoring runs were manual. Changing cron to non-peak minutes and committing the new workflow configuration is a mitigation, **not proof** that the scheduler is now firing. Check `event=schedule` over the next several schedule windows. If it remains zero, investigate workflow activation, actor and GitHub scheduler status. No monitoring uptime guarantee can be claimed yet.

### Priority 1 — account-specific visibility

Our OpenAI model list had 127 entries; the external Aurora report claimed 144 for a separate API account. This discrepancy is **not resolved by software changes**. Different accounts/projects may see different available model IDs. We cannot validate the claim without authorized independent evidence or access. **Do not claim that Aurora is confirmed by OpenAI.**

### Priority 1 — detection coverage

The current pipeline monitors four catalogs and three official Python SDK repositories, not third-party observations, developer posts or all SDK languages. The conservative ID parser only recognizes selected model prefixes. This is the next development phase once the monitor is proven reliable.

### Priority 2 — history retention and model metadata

The public snapshot stores model IDs rather than provider `created` metadata and owner fields. First-seen means when our tracker observed an ID, not when it was created. Expanding metadata capture needs privacy/semantics review, backfill rules and tests.

### Priority 2 — SDK and Telegram edge cases

GitHub returns up to 30 recent commits per repo; if a checkpoint leaves this window during an outage, the tracker logs the coverage gap and baselines forward. Two detailed patches per SDK per scan are allowed, so backlogs recover gradually. A Telegram send may succeed while a later Git commit fails; retries can then produce **duplicate** alerts (at-least-once, not exactly-once). A multipart Telegram message can similarly partially repeat after transport failure.

### Priority 2 — GitHub Action persistence and source failures

State is committed by the GitHub monitor job. External concurrent pushes, disabled Actions, repository rate limits, credential expiry, or GitHub scheduler failures can delay/stop monitoring. The newly added `_health` object exposes source failures, but does not automatically fix them.

### Priority 3 — false positives / launch classification

Generic release-note and commit-message keyword matching can be noisy. Candidate IDs are restricted to recognizable patterns and may miss deliberately opaque codenames. Multiple reports copying the same source must not count as independent confirmation. A source-code reference or API ID is **not** a public-release announcement.

### Priority 3 — publishing dashboard and wider public intelligence

GitHub Pages, additional official documentation, external researcher posts, and public Telegram/X publication have **not** yet been implemented. Public posts must distinguish `unverified`, `catalog_observation`, `official_code_signal`, and `official_release_note`.

## Security review

No committed `.env` or token file appeared in the audited tracked-file tree. `.gitignore` excludes common local environment files. Actions secrets are referenced by variable names, but their values were not read. The tracker logs exception classes / HTTP status categories, not secret-bearing request headers. Built-in `GH_API_TOKEN` is attached only for `https://api.github.com/` requests, and a unit test guards against sending it to the OpenAI provider URL.

Public evidence and pending alerts may include **public** SDK code snippets or public model identifiers; avoid adding secrets, nonpublic research, Telegram IDs or raw confidential API responses to the repository.

## Suggested next work after verification

1. Confirm at least one real scheduled monitor run, full-provider collection, GitHub SDK monitoring, state commit, and retry queue behavior without manual execution.
2. Add authorized, evidence-linked official documentation and independent-source observations, labelled as claims until verified.
3. Capture safe model metadata (created/owner where provided) and compare first-seen versus provider timestamps.
4. Build a free searchable evidence dashboard and public alerts only after attribution and deduplication pass quality gates.

## Sources

- [GitHub Actions scheduling limitations](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)
- [Anthropic List Models API](https://platform.claude.com/docs/en/api/models/list)
- [Gemini models.list API](https://ai.google.dev/api/models)
