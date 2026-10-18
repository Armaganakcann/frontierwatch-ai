"""Public model catalog tracker; standard library only."""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

STATE = Path("data/models.json")

def normalize_models(items):
    return sorted({(m.get("id") or m.get("name")) for m in items if isinstance(m, dict) and isinstance(m.get("id") or m.get("name"), str)})

def diff_models(previous, current, initial=False):
    if initial:
        return {}
    return {provider: sorted(set(ids) - set(previous.get(provider, [])))
            for provider, ids in current.items()
            if provider in previous and set(ids) - set(previous.get(provider, []))}

def fetch(url, headers):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)

def collect():
    sources = {
        "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1/models", "Authorization", "Bearer "),
        "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/models?limit=100", "x-api-key", ""),
        "google": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", "x-goog-api-key", ""),
    }
    result = {}
    for provider, (env, url, header, prefix) in sources.items():
        key = os.environ.get(env)
        if not key:
            print(f"{provider}: skipped (missing {env})")
            continue
        headers = {header: prefix + key}
        if provider == "anthropic":
            headers["anthropic-version"] = "2023-06-01"
        try:
            data = fetch(url, headers)
            if data.get("has_more") or data.get("nextPageToken"):
                raise ValueError("Paginated response; refusing incomplete snapshot")
            items = data.get("models" if provider == "google" else "data", [])
            result[provider] = normalize_models(items)
        except Exception as exc:
            print(f"{provider}: collection failed: {type(exc).__name__}", file=sys.stderr)
    try:
        data = fetch("https://openrouter.ai/api/v1/models", {"User-Agent": "FrontierWatchAI/0.2"})
        items = data.get("data")
        if not isinstance(items, list):
            raise ValueError("Missing OpenRouter data array")
        result["openrouter"] = normalize_models(items)
        print(f"openrouter: {len(result['openrouter'])} catalog IDs collected")
    except Exception as exc:
        print(f"openrouter: collection failed: {type(exc).__name__}", file=sys.stderr)
    for provider, ids in result.items():
        if provider != "openrouter":
            print(f"{provider}: {len(ids)} catalog IDs collected")
    return result


SDK_REPOS = {
    "openai-python": "openai/openai-python",
    "anthropic-sdk-python": "anthropics/anthropic-sdk-python",
    "python-genai": "googleapis/python-genai",
}

def classify_release(body):
    import re
    return bool(re.search(r"\\b(model|models|identifier|gemini|claude|gpt|aurora)\\b", body, re.I))

def collect_sdk_releases():
    releases = {}
    for label, repo in SDK_REPOS.items():
        try:
            data = fetch(f"https://api.github.com/repos/{repo}/releases/latest",
                         {"Accept": "application/vnd.github+json",
                          "User-Agent": "FrontierWatchAI/0.3"})
            tag, url = data.get("tag_name"), data.get("html_url")
            if not isinstance(tag, str) or not isinstance(url, str):
                raise ValueError("Missing release tag or URL")
            releases[label] = {"tag": tag, "url": url, "body": str(data.get("body") or "")[:10000]}
            print(f"sdk {label}: {tag}")
        except Exception as exc:
            print(f"sdk {label}: collection failed: {type(exc).__name__}", file=sys.stderr)
    return releases

def release_signals(previous, current):
    messages = []
    for label, release in current.items():
        if label not in previous or previous[label] == release["tag"]:
            continue
        body = release["body"]
        if classify_release(body):
            matches = [line.strip() for line in body.splitlines()
                       if classify_release(line) and len(line.strip()) > 8]
            excerpt = " | ".join(matches[:3])[:450]
            messages.append(f"OFFICIAL SDK RELEASE SIGNAL (not a model release)\\n{label}: {release['tag']}\\n{excerpt}\\n{release['url']}")
    return messages

def notify(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram credentials missing; no alert sent")
        return False
    payload = json.dumps({"chat_id": chat, "text": message}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as response:
        response.read()
    return True

def main():
    previous = json.loads(STATE.read_text()) if STATE.exists() else {}
    current = collect()
    if not current:
        print("No successful sources; state unchanged")
        return
    sdk = collect_sdk_releases()
    changes = diff_models(previous, current)
    if changes:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [f"FrontierWatch AI — new catalog IDs ({stamp})"]
        for provider, ids in changes.items():
            lines.append(f"{provider}: {', '.join(ids)}")
        lines.append("Catalog observation only; not evidence of public release.")
        notify("\n".join(lines))
    for signal in release_signals(previous.get('_sdk_releases', {}), sdk):
        notify(signal)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {**previous, **current}
    snapshot['_sdk_releases'] = {**previous.get('_sdk_releases', {}), **{k: v['tag'] for k, v in sdk.items()}}
    if not previous.get("_telegram_test_sent"):
        if notify("FrontierWatch AI test: Telegram connection is working. Model catalog monitoring is active."):
            snapshot["_telegram_test_sent"] = True
            print("Telegram test message delivered to Telegram API")
    STATE.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")

if __name__ == "__main__":
    main()
