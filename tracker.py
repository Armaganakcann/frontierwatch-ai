"""Public model catalog tracker; standard library only."""
import json
import os
import sys
import urllib.request
import urllib.error
from urllib.parse import quote
from datetime import datetime, timezone
from pathlib import Path
from intelligence import extract_model_ids, merge_evidence, model_summary

STATE = Path("data/models.json")

def normalize_models(items):
    """Normalize non-empty, string model IDs; do not invent missing identifiers."""
    ids = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        for field in ("id", "name"):
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                ids.add(value.strip())
                break
    return sorted(ids)

def validate_catalog(items, provider, previous=None):
    """Fail closed when a provider returns malformed or unexpectedly tiny data."""
    if not isinstance(items, list):
        raise ValueError(f"{provider}: expected list")
    ids = normalize_models(items)
    if not ids:
        raise ValueError(f"{provider}: empty model catalog")
    if previous and len(ids) < max(1, (len(previous) + 1) // 2):
        raise ValueError(f"{provider}: suspicious catalog shrink ({len(previous)} -> {len(ids)})")
    return ids

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


def fetch_catalog_pages(provider, url, headers, max_pages=20):
    """Retrieve every accessible provider page or fail without a partial snapshot."""
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    all_items = []
    seen_cursors = set()
    cursor = None
    for _ in range(max_pages):
        page_url = url
        if cursor is not None:
            parameter = "after_id" if provider == "anthropic" else "pageToken"
            page_url += "&" + parameter + "=" + quote(cursor, safe="")
        response = fetch(page_url, headers)
        if not isinstance(response, dict):
            raise ValueError(f"{provider}: invalid catalog response")
        field = "models" if provider == "google" else "data"
        items = response.get(field)
        if not isinstance(items, list):
            raise ValueError(f"{provider}: missing {field} array")
        all_items.extend(items)
        if provider == "anthropic":
            if not isinstance(response.get("has_more"), bool):
                raise ValueError("anthropic: missing has_more pagination flag")
            next_cursor = response.get("last_id") if response["has_more"] else None
        elif provider == "google":
            next_cursor = response.get("nextPageToken")
        elif provider == "openai":
            if response.get("has_more") or response.get("nextPageToken"):
                raise ValueError("openai: unexpected pagination; refusing partial catalog")
            next_cursor = None
        else:
            raise ValueError(f"Unsupported catalog provider: {provider}")
        if not next_cursor:
            if provider == "anthropic" and response["has_more"]:
                raise ValueError("anthropic: more pages but no last_id")
            return all_items
        if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
            raise ValueError(f"{provider}: invalid or repeated page cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    raise ValueError(f"{provider}: pagination exceeded {max_pages} pages")

def collect(previous=None, diagnostics=None):
    previous = previous or {}
    diagnostics = diagnostics if diagnostics is not None else {}
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
            diagnostics[provider] = {"status": "missing_key"}
            continue
        headers = {header: prefix + key}
        if provider == "anthropic":
            headers["anthropic-version"] = "2023-06-01"
        try:
            items = fetch_catalog_pages(provider, url, headers)
            result[provider] = validate_catalog(items, provider, previous.get(provider))
            diagnostics[provider] = {"status": "ok", "count": len(result[provider])}
        except Exception as exc:
            error = f"HTTP_{exc.code}" if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
            diagnostics[provider] = {"status": "failed", "error": error}
            print(f"{provider}: collection failed: {error}", file=sys.stderr)
    try:
        data = fetch("https://openrouter.ai/api/v1/models", {"User-Agent": "FrontierWatchAI/0.2"})
        items = data.get("data")
        if not isinstance(items, list):
            raise ValueError("Missing OpenRouter data array")
        result["openrouter"] = validate_catalog(items, "openrouter", previous.get("openrouter"))
        diagnostics["openrouter"] = {"status": "ok", "count": len(result["openrouter"])}
        print(f"openrouter: {len(result['openrouter'])} catalog IDs collected")
    except Exception as exc:
        error = f"HTTP_{exc.code}" if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
        diagnostics["openrouter"] = {"status": "failed", "error": error}
        print(f"openrouter: collection failed: {error}", file=sys.stderr)
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
    if not any(item.get("sha") == previous_sha for item in commits):
        print(f"commits {label}: previous SHA outside window; skipping")
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
    """Find explicit candidate IDs in newly added SDK source lines."""
    findings = []
    ids = set()
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
            candidates = extract_model_ids(added)
            if not candidates:
                continue
            ids.update(candidates)
            findings.append(f"{name}: {added[:180]}")
            if len(findings) >= 3:
                break
        if len(findings) >= 3:
            break
    if not findings:
        return []
    return [f"OFFICIAL SOURCE CODE SIGNAL (not a model release)\n{label} {sha[:12]}\n"
            + "Candidate IDs: " + ", ".join(sorted(ids)) + "\n"
            + "\n".join(findings) + f"\n{url}"]

def collect_patch_signals(previous, commits, per_provider_limit=2):
    """Scan SDK patches oldest-first, checkpointing only successfully inspected commits.

    Keeping a separate checkpoint from the commit-message cursor prevents losing
    uninspected patches when there are more updates than the per-run budget.
    """
    signals = []
    checkpoints = {}
    for label, entries in commits.items():
        old = previous.get(label)
        if not old:
            # First sight of a repo is a baseline, not a retrospective alert.
            checkpoints[label] = entries[0]["sha"]
            continue
        selected = []
        for entry in entries:
            if entry.get("sha") == old:
                break
            selected.append(entry)
        else:
            print(f"patches {label}: checkpoint outside 30-commit window; gap in coverage",
                  file=sys.stderr)
            # The gap is unavoidable with this API window. Start a new baseline.
            checkpoints[label] = entries[0]["sha"]
            continue
        checkpoint = old
        for entry in list(reversed(selected))[:per_provider_limit]:
            sha = entry.get("sha")
            if not isinstance(sha, str):
                break
            try:
                detail = fetch(f"https://api.github.com/repos/{SDK_REPOS[label]}/commits/{sha}",
                               {"Accept": "application/vnd.github+json",
                                "User-Agent": "FrontierWatchAI/0.5"})
                if not isinstance(detail.get("files"), list):
                    raise ValueError("missing GitHub commit files")
                signals.extend(patch_signals(label, sha, entry.get("html_url", ""),
                                             detail["files"]))
                checkpoint = sha
            except Exception as exc:
                print(f"patches {label}: detail unavailable ({type(exc).__name__}); will retry",
                      file=sys.stderr)
                break
        checkpoints[label] = checkpoint
    return signals, checkpoints

def queue_alerts(existing, new):
    """Preserve order without queueing the same unsent notification twice."""
    return list(dict.fromkeys([*existing, *new]))

def deliver_alerts(pending, sender, limit=8):
    """Try bounded Telegram delivery; failed alerts remain queued for retry."""
    if limit < 0:
        raise ValueError("limit must be non-negative")
    remaining = []
    for index, message in enumerate(pending):
        if index >= limit:
            remaining.append(message)
            continue
        try:
            if not sender(message):
                remaining.append(message)
        except Exception as exc:
            print(f"Telegram delivery failed: {type(exc).__name__}; will retry",
                  file=sys.stderr)
            remaining.append(message)
    return remaining

def chunk_message(message, limit=4000):
    """Keep every character while respecting Telegram message size limits."""
    if limit < 1:
        raise ValueError("limit must be positive")
    return [message[i:i + limit] for i in range(0, len(message), limit)] or [""]

def notify(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram credentials missing; no alert sent")
        return False
    for piece in chunk_message(message):
        payload = json.dumps({"chat_id": chat, "text": piece}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as response:
            response.read()
    return True

def main():
    """Run sources independently; persist evidence and retryable alerts atomically."""
    previous = json.loads(STATE.read_text()) if STATE.exists() else {}
    if not isinstance(previous, dict):
        raise ValueError("Invalid previous snapshot: expected JSON object")
    catalog_health = {}
    current = collect(previous, diagnostics=catalog_health)
    if not current:
        print("No successful catalogs; preserving previous model lists")
    sdk = collect_sdk_releases()
    commits = collect_sdk_commits()

    alerts = []
    evidence_incoming = []
    changes = diff_models(previous, current)
    if changes:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [f"FrontierWatch AI — new catalog IDs ({stamp})"]
        for provider, ids in changes.items():
            lines.append(f"{provider}: {', '.join(ids)}")
            reference = {"openai": "https://api.openai.com/v1/models",
                         "anthropic": "https://api.anthropic.com/v1/models",
                         "google": "https://generativelanguage.googleapis.com/v1beta/models",
                         "openrouter": "https://openrouter.ai/api/v1/models"}.get(provider)
            for model in ids:
                if reference:
                    evidence_incoming.append({"model": model, "source": "catalog",
                                              "provider": provider, "reference": reference})
        lines.append("Catalog observation only; not evidence of public release.")
        alerts.append("\n".join(lines))

    prior_releases = previous.get("_sdk_releases", {})
    for label, release in sdk.items():
        for signal in release_signals(prior_releases, {label: release}):
            alerts.append(signal)
            for model in extract_model_ids(signal):
                evidence_incoming.append({"model": model, "source": "sdk_release",
                                          "provider": label, "reference": release["url"]})

    prior_patch_cursors = previous.get("_sdk_patch_commits",
                                       previous.get("_sdk_commits", {}))
    patch_alerts, patch_cursors = collect_patch_signals(prior_patch_cursors, commits)
    for signal in patch_alerts:
        alerts.append(signal)
        lines = signal.splitlines()
        ref = lines[-1] if lines else ""
        provider = lines[1].split()[0] if len(lines) > 1 else ""
        if ref.startswith("https://github.com/") and provider in SDK_REPOS:
            for model in extract_model_ids(signal):
                evidence_incoming.append({"model": model, "source": "sdk_patch",
                                          "provider": provider, "reference": ref})

    for label, entries in commits.items():
        for signal in commit_signals(label, previous.get("_sdk_commits", {}).get(label), entries):
            alerts.append(signal)
            ref = signal.rsplit("\n", 1)[-1]
            if ref.startswith("https://github.com/"):
                for model in extract_model_ids(signal):
                    evidence_incoming.append({"model": model, "source": "sdk_commit",
                                              "provider": label, "reference": ref})

    evidence, fresh_evidence = merge_evidence(previous.get("_evidence", []), evidence_incoming,
                                              datetime.now(timezone.utc).isoformat())
    print(f"evidence: {len(evidence)} records ({len(fresh_evidence)} new)")
    snapshot = {**previous, **current}
    snapshot["_evidence"] = evidence
    snapshot["_model_summary"] = model_summary(evidence)
    snapshot["_sdk_patch_commits"] = {**prior_patch_cursors, **patch_cursors}
    snapshot["_sdk_commits"] = {**previous.get("_sdk_commits", {}),
                                **{label: items[0]["sha"] for label, items in commits.items()}}
    snapshot["_sdk_releases"] = {**previous.get("_sdk_releases", {}),
                                 **{label: item["tag"] for label, item in sdk.items()}}

    queued = queue_alerts(previous.get("_pending_alerts", []), alerts)
    pending = deliver_alerts(queued, notify)
    snapshot["_pending_alerts"] = pending
    snapshot["_health"] = {"catalogs": catalog_health,
                           "sdk_releases": {k: ("ok" if k in sdk else "unavailable") for k in SDK_REPOS},
                           "sdk_commits": {k: ("ok" if k in commits else "unavailable") for k in SDK_REPOS},
                           "telegram_pending": len(pending)}
    if pending:
        print(f"Telegram: {len(pending)} alert(s) queued for retry")

    if not previous.get("_telegram_test_sent"):
        try:
            if notify("FrontierWatch AI test: Telegram connection is working. Model catalog monitoring is active."):
                snapshot["_telegram_test_sent"] = True
                print("Telegram test message delivered to Telegram API")
        except Exception as exc:
            print(f"Telegram connectivity test failed: {type(exc).__name__}", file=sys.stderr)

    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    temporary.replace(STATE)

if __name__ == "__main__":
    main()
