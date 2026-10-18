"""Public model catalog tracker; standard library only."""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from intelligence import extract_model_ids, evidence_level

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
    return bool(re.search(r"\b(model|models|identifier|gemini|claude|gpt|aurora)\b", body, re.I))

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
            messages.append(f"OFFICIAL SDK RELEASE SIGNAL (not a model release)\n{label}: {release['tag']}\n{excerpt}\n{release['url']}")
    return messages


def commit_signals(label, previous_sha, commits):
    if not previous_sha:
        return []
    messages = []
    for item in commits:
        if item.get("sha") == previous_sha:
            break
        message = item.get("commit", {}).get("message", "")
        url = item.get("html_url", "")
        if classify_release(message) and url.startswith("https://github.com/"):
            messages.append(f"OFFICIAL COMMIT SIGNAL (not a model release)\n{label}: {message[:280]}\n{url}")
    return messages[:5]

def collect_sdk_commits():
    results = {}
    for label, repo in SDK_REPOS.items():
        try:
            data = fetch(f"https://api.github.com/repos/{repo}/commits?per_page=30",
                         {"Accept": "application/vnd.github+json", "User-Agent": "FrontierWatchAI/0.4"})
            if not isinstance(data, list) or not data or not isinstance(data[0].get("sha"), str):
                raise ValueError("Invalid commits response")
            results[label] = data
            print(f"commits {label}: latest {data[0]['sha'][:12]}")
        except Exception as exc:
            print(f"commits {label}: collection failed: {type(exc).__name__}", file=sys.stderr)
    return results


def patch_signals(label, sha, url, files):
    """Only newly added model-related source lines; not docs or tests."""
    import re
    findings = []
    for item in files:
        name = item.get("filename", "")
        if (not name.endswith((".py", ".ts", ".js", ".json")) or
                any(part in name.lower().split("/") for part in
                    ("tests", "test", "docs", "examples", "fixtures", "samples"))):
            continue
        for line in (item.get("patch") or "").splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue
            added = line[1:].strip()
            if len(added) > 250:
                continue
            if re.search(r"(?i)(model[_-]?(id|name)?|aurora|gemini|claude|gpt)[^\n]{0,100}", added):
                findings.append(f"{name}: {added[:180]}")
            if len(findings) >= 3:
                break
        if len(findings) >= 3:
            break
    if not findings:
        return []
    ids = sorted({model for finding in findings for model in extract_model_ids(finding)})
    ids_line = ("\nCandidate IDs: " + ", ".join(ids)) if ids else ""
    return [f"OFFICIAL SOURCE CODE SIGNAL (not a model release)\n{label} {sha[:12]}{ids_line}\n" +
            "\n".join(findings) + f"\n{url}"]

def collect_patch_signals(previous, commits):
    signals = []
    for label, entries in commits.items():
        old = previous.get(label)
        if not old:
            continue
        selected = []
        for entry in entries:
            if entry.get("sha") == old:
                break
            selected.append(entry)
        else:
            # Avoid treating an incomplete 30-commit window as exhaustive.
            print(f"patches {label}: prior commit outside window; skipping")
            continue
        for entry in reversed(selected[:5]):
            sha = entry.get("sha")
            if not isinstance(sha, str):
                continue
            try:
                detail = fetch(f"https://api.github.com/repos/{SDK_REPOS[label]}/commits/{sha}",
                               {"Accept": "application/vnd.github+json",
                                "User-Agent": "FrontierWatchAI/0.5"})
                signals.extend(patch_signals(label, sha, entry.get("html_url", ""),
                                             detail.get("files", [])))
            except Exception as exc:
                print(f"patches {label}: {type(exc).__name__}", file=sys.stderr)
    return signals[:10]

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
    commits = collect_sdk_commits()
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
    for signal in collect_patch_signals(previous.get("_sdk_commits", {}), commits):
        notify(signal)
    for label, entries in commits.items():
        for signal in commit_signals(label, previous.get("_sdk_commits", {}).get(label), entries):
            notify(signal)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {**previous, **current}
    snapshot['_sdk_commits'] = {**previous.get('_sdk_commits', {}), **{k: v[0]['sha'] for k, v in commits.items()}}
    snapshot['_sdk_releases'] = {**previous.get('_sdk_releases', {}), **{k: v['tag'] for k, v in sdk.items()}}
    if not previous.get("_telegram_test_sent"):
        if notify("FrontierWatch AI test: Telegram connection is working. Model catalog monitoring is active."):
            snapshot["_telegram_test_sent"] = True
            print("Telegram test message delivered to Telegram API")
    STATE.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")

if __name__ == "__main__":
    main()
