# FrontierWatch AI

Open-source, **zero paid-inference** model-catalog and official SDK signal tracker. It monitors publicly available catalogs and authorized API model lists and can send Telegram alerts when changes are observed.

## Data sources

| Source | Information | Access |
| --- | --- | --- |
| OpenAI `GET /v1/models` | Models visible to **this API key** | `OPENAI_API_KEY` |
| Anthropic `GET /v1/models` | Visible model IDs, all available pages | `ANTHROPIC_API_KEY` |
| Google Gemini `models.list` | Visible model IDs, all available pages | `GEMINI_API_KEY` |
| OpenRouter `/api/v1/models` | Public model catalog IDs | No key |
| Official OpenAI / Anthropic / Google Python and JavaScript/TypeScript SDK GitHub repos (6 total) | Releases, recent commit messages, newly added source code | GitHub Actions built-in token |
| Official OpenAI OpenAPI schema repository | Commits and added model literals in YAML/JSON schema | GitHub Actions built-in token |
| Public Hacker News Algolia search (4 focused queries) | Recent posts containing recognizable model IDs (not model verification) | No key |

**The tracker does not call inference/completion endpoints.** Listing APIs may still have provider requirements or quotas; check your account terms.

## Running the system

- `.github/workflows/monitor.yml`: scheduled approximately every 15 minutes at UTC minutes 07, 22, 37 and 52, plus optional manual dispatch. GitHub may delay or drop schedules.
- `.github/workflows/ci.yml`: tests on Python source/test changes or pull requests; does **not** send Telegram messages or query paid model APIs.
- Test locally: `python -m unittest discover -s tests -v` (Python 3.12, standard library).
- All credentials belong in repository Actions secrets, never code or `data/models.json`. The GitHub API token is provided automatically to the monitoring job.

See [SETUP.md](SETUP.md) to configure Telegram and secrets.

## Evidence and persistence

`data/models.json` stores:
- Provider catalog ID lists;
- \`_catalog_metadata\`: allowlisted provider-reported creation dates and owner fields (when supplied), **distinct from our first-seen timestamp**;
- `_sdk_releases` and `_sdk_commits` for release/commit-message baselines;
- `_sdk_patch_commits` for **independent, incremental source patch checkpoints**;
- `_evidence` and `_model_summary` for first-observed signals and their source classification;
- `_pending_alerts` for Telegram delivery retries;
- `_health` for sanitized provider connectivity and pending-alert information.

Provider lists must be nonempty and well-formed. Sudden reductions exceeding 50% are refused to avoid overwriting known-good snapshots. Anthropic/Gemini pagination is followed completely with repeat-cursor and maximum-page guards; errors do not create partial baselines. When providers fail, their previous successful lists remain.

Hacker News evidence is labelled **\`community\` / \`unverified\`**. Search is bounded by a recent time window, query count and page budget. It monitors public HN stories only; it is **not direct X/Twitter access**, not a complete media search, and not verification of a provider API. The first successful community scan establishes a silent baseline; subsequent new references may trigger an explicitly unverified Telegram notice.

GitHub source patches are checked incrementally, at most two per official repository per run. Older changes can still be missed when the last checkpoint is outside the most recent 30 commits; that is logged as an explicit coverage gap. Telegram alerts use a retry queue, with at-least-once semantics (rare duplicate sends are possible).

## Interpretation

A catalog ID, SDK release note, commit, or patch is **not confirmation of a model launch**. A named rumored model is not confirmed merely by appearing in someone else's post. Model visibility can vary by API key or provider account. First-seen timestamps are tracker observations, not necessarily model creation dates.

Catalog alerts: `catalog_observation`; source-code signals: `official_code_signal`; SDK commit/release notes have separate levels; unsupported claims remain `unverified`.

**Security:** Repository snapshot files and source evidence are public. Do not include credentials, Telegram chat IDs, private conversations, or private endpoints. The monitor's GitHub token is attached only to `api.github.com` requests.

See [AUDIT.md](AUDIT.md) for verified fixes, residual risks, and the next development priorities.

## Independent listing signals

`external_signals.py` reads public ClaudeMon model-listing observations, keeps explicit links to the reported documentation URL, and labels every result **`unverified`**. It does not access another user's API key or prove model availability. Only recent events (14 days) are eligible for new discovery; old feed history is not replayed as fresh alerts. Official-looking URLs are validated by HTTPS hostname, not a string prefix. The fetch and parser are bounded, and source failures are recorded under `_health.external_listings`.

**Aurora case:** Three records (`aurora-blue-alpha`, `aurora-green-alpha`, `aurora-red-alpha`) were first observed by this tracker via ClaudeMon on 2026-10-18; their upstream timestamps are 2026-10-17. These are external observations, not independent authenticated OpenAI model-list verification. The OpenAI account used by this monitor still did not list Aurora at that time.


## Scheduling proof and independent release aggregation

The workflow requests a 15-minute GitHub Actions cron at UTC minutes 07, 22, 37 and 52. **A successful push-triggered run does not prove the cron fired.** The snapshot now stores `_last_run.completed_at`, `_last_run.trigger` and `_last_run.run_id`, allowing inspection of the latest completed invocation. To verify native scheduling, inspect GitHub Actions runs filtered by `event=schedule` and confirm a successful run; GitHub's scheduler is best-effort and may be delayed or skipped. No zero-downtime SLA is implied.

The additional independent release source is AIDataHub's public `/api/model-releases.json` archive. Only non-baseline, recently published, source-linked `release` records from an allowlisted provider are eligible; `listing` records are **not** elevated to releases. Each observation retains the primary-source URL and is explicitly tagged `external_release`, not direct API access. Health is visible in `_health.independent_releases`. Documentation: https://www.aidatahub.io/docs/model-releases. The provider states a recommended polling interval of at least 15 minutes; this workflow observes that cadence.
