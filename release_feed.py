"""Independent AIDataHub public official-release aggregation, not direct API access."""
from datetime import datetime, timezone
from urllib.parse import urlsplit
from intelligence import evidence_key, extract_model_ids

URL = "https://www.aidatahub.io/api/model-releases.json"
PROVIDER_HOSTS = {
    "openai": {"openai.com", "developers.openai.com", "platform.openai.com"},
    "anthropic": {"anthropic.com", "docs.anthropic.com", "platform.claude.com"},
    "google": {"ai.google.dev", "developers.googleblog.com", "blog.google", "deepmind.google"},
    "xai": {"x.ai", "docs.x.ai"},
    "mistral": {"mistral.ai", "docs.mistral.ai"},
    "deepseek": {"api-docs.deepseek.com", "deepseek.com"},
    "cohere": {"cohere.com", "docs.cohere.com"},
    "qwen": {"qwenlm.github.io", "alibabacloud.com"}
}

def parse_release_feed(document, *, now=None, max_age_days=14):
    if not isinstance(document, dict) or document.get("schemaVersion") != 1 or not isinstance(document.get("events"), list):
        raise ValueError("Unexpected release feed schema")
    if len(document["events"]) > 10000:
        raise ValueError("Excessive release feed size")
    now = now or datetime.now(timezone.utc)
    records = {}
    for event in document["events"]:
        if not isinstance(event, dict) or event.get("type") != "release" or event.get("baseline") is not False:
            continue
        provider = event.get("provider")
        model = event.get("modelId")
        source = event.get("sourceUrl")
        published = event.get("publishedAt")
        if not isinstance(provider, str) or provider.lower() not in PROVIDER_HOSTS:
            continue
        if not isinstance(model, str) or not isinstance(source, str) or not isinstance(published, str):
            continue
        if model.lower() not in extract_model_ids(model):
            continue
        parsed = urlsplit(source)
        if parsed.scheme != "https" or parsed.hostname not in PROVIDER_HOSTS[provider.lower()] or parsed.username or parsed.password:
            continue
        try:
            published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            continue
        if published_at.tzinfo is None or not 0 <= (now - published_at).total_seconds() <= max_age_days * 86400:
            continue
        record = {"model": model, "provider": "aidatahub", "source": "external_release",
                  "reference": source, "origin_provider": provider.lower(),
                  "published_at": published, "observation_url": URL}
        records[evidence_key(record)] = record
    return list(records.values())

def collect_release_feed(fetch_json):
    try:
        entries = parse_release_feed(fetch_json(URL, {"User-Agent": "FrontierWatchAI/1.0",
                                                       "Accept": "application/json"}))
        return entries, {"status": "ok", "observations": len(entries)}
    except Exception:
        return [], {"status": "failed", "observations": 0}

def release_feed_alerts(fresh, limit=5):
    records = [r for r in fresh if r.get("source") == "external_release"]
    if not records:
        return []
    lines = ["FrontierWatch AI — EXTERNAL release-feed observation",
             "Reported as official release by a third-party aggregator; verify primary source and account access."]
    for item in records[:limit]:
        lines.extend([item["model"], item["reference"]])
    return ["\n".join(lines)]
