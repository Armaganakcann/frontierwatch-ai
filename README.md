# FrontierWatch AI

Free, public-source model-catalog and official SDK change monitoring. Runs on GitHub Actions without paid model inference.

## Sources
- OpenAI, Anthropic, Google Gemini model-list endpoints (requires user-provided API keys; no model inference).
- OpenRouter public model catalog (no API key required).
- Official Python SDK GitHub release notes, commit messages, and newly added source-code lines for OpenAI, Anthropic, and Google.

## Evidence and limitations
- New catalog IDs are **catalog observations**, not proof of a public launch.
- SDK release notes, commits, and source-code additions are **signals**, not announcements.
- The candidate ID extractor is conservative (e.g. `aurora-blue`, `gpt-6-preview`); it can miss unknown naming patterns.
- State and evidence are committed in `data/models.json` under `_evidence` and `_model_summary`. These records are **public**. Never put API keys or personal data in them.
- Initial scans establish baselines. Source failures preserve the last successful snapshot.
- GitHub Actions is configured for 15-minute cron intervals, but actual scheduling may be delayed.
- GitHub's unauthenticated API rate limits, 30-commit window, and up-to-five detailed patch checks per source can cause missed changes.
- Model identity matching and evidence grouping are not proof of availability, release, authenticity, or ownership.
- Telegram notifications are sent only when relevant new changes are detected, except for the initial one-time connectivity test.

## Operations
The workflow `.github/workflows/monitor.yml` runs tests, collects sources, and commits the state automatically. Manual runs are optional. Check [Actions](https://github.com/Armaganakcann/frontierwatch-ai/actions) only if an automatic run fails.

Required GitHub Actions secrets: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

Tests: `python -m unittest discover -s tests -v`.

This project does not access private provider systems, bypass access controls, or establish the existence of rumored models.
