# FrontierWatch AI

Open-source, **zero paid-inference** model-catalog and official SDK signal tracker. It monitors publicly available catalogs and authorized API model lists and can send Telegram alerts when changes are observed.

## Data sources

| Source | Information | Access |
| --- | --- | --- |
| OpenAI `GET /v1/models` | Models visible to **this API key** | `OPENAI_API_KEY` |
| Anthropic `GET /v1/models` | Visible model IDs, all available pages | `ANTHROPIC_API_KEY` |
| Google Gemini `models.list` | Visible model IDs, all available pages | `GEMINI_API_KEY` |
| OpenRouter `/api/v1/models` | Public model catalog IDs | No key |
| Official OpenAI / Anthropic / Google Python SDK GitHub repos | Releases, recent commit messages, newly added source code | GitHub Actions built-in token |

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
- `_sdk_releases` and `_sdk_commits` for release/commit-message baselines;
- `_sdk_patch_commits` for **independent, incremental source patch checkpoints**;
- `_evidence` and `_model_summary` for first-observed signals and their source classification;
- `_pending_alerts` for Telegram delivery retries;
- `_health` for sanitized provider connectivity and pending-alert information.

Provider lists must be nonempty and well-formed. Sudden reductions exceeding 50% are refused to avoid overwriting known-good snapshots. Anthropic/Gemini pagination is followed completely with repeat-cursor and maximum-page guards; errors do not create partial baselines. When providers fail, their previous successful lists remain.

GitHub source patches are checked incrementally, at most two per SDK per run. Older changes can still be missed when the last checkpoint is outside the most recent 30 commits; that is logged as an explicit coverage gap. Telegram alerts use a retry queue, with at-least-once semantics (rare duplicate sends are possible).

## Interpretation

A catalog ID, SDK release note, commit, or patch is **not confirmation of a model launch**. A named rumored model is not confirmed merely by appearing in someone else's post. Model visibility can vary by API key or provider account. First-seen timestamps are tracker observations, not necessarily model creation dates.

Catalog alerts: `catalog_observation`; source-code signals: `official_code_signal`; SDK commit/release notes have separate levels; unsupported claims remain `unverified`.

**Security:** Repository snapshot files and source evidence are public. Do not include credentials, Telegram chat IDs, private conversations, or private endpoints. The monitor's GitHub token is attached only to `api.github.com` requests.

See [AUDIT.md](AUDIT.md) for verified fixes, residual risks, and the next development priorities.
