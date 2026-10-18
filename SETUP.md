# FrontierWatch AI — setup and operations

1. Start the Telegram bot [@FrontierWatchAIBot](https://t.me/FrontierWatchAIBot) using `/start`.
2. In **GitHub → repository Settings → Secrets and variables → Actions**, configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. For authenticated model catalogs, add `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` as appropriate. Missing keys skip that provider; OpenRouter can still run without a key.
4. GitHub provides its own `github.token` automatically for authenticated GitHub API requests, so **do not add a personal GitHub token**.
5. Monitor workflow: `.github/workflows/monitor.yml`, UTC at 07, 22, 37, 52 minutes; manual runs are optional. GitHub schedules can be delayed or skipped.
6. Independent CI: `.github/workflows/ci.yml`; tests run on code changes without the model API or Telegram credentials.

Test locally with `python -m unittest discover -s tests -v` (Python 3.12).

Public state: `data/models.json`. Never put secrets or personal information in this file. The monitor saves latest complete provider catalogs, sanitized source health, a retryable Telegram alert queue and source evidence there.

**Troubleshooting:** Look at the repository's Actions tab. For a successful monitor job, inspect `Monitor catalogs` logs for per-provider model counts and SDK results. Inspect `_health` for `missing_key`, `failed` and HTTP status categories. Model-list endpoints do not mean inference permission, and a listed ID is not proof of a released model.

**Known limitations:** GitHub scheduled events are not guaranteed on time. Account-specific model visibility may prevent seeing a model another researcher sees. SDK patch monitoring covers only recent public commits. Inspect [AUDIT.md](AUDIT.md) for the known gaps and resolutions.
