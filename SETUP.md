# FrontierWatch AI setup

1. Open @FrontierWatchAIBot on Telegram and send /start.
2. Keep the BotFather token private.
3. In GitHub repository Settings > Secrets and variables > Actions, add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
4. Add any API credentials you have: OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY.
5. Enable Actions and run Monitor public model catalogs manually to initialize a baseline.
6. Subsequent runs are scheduled every 15 minutes but GitHub may delay or skip runs.

The initial snapshot does not send notifications. Catalog listing may require provider billing setup. No inference requests are sent. Failed providers retain prior state. This MVP rejects paginated results rather than misrepresenting partial catalogs; pagination support is planned. Model IDs do not prove a public release.

Run tests: python -m unittest discover -s tests -v
