"""Third-party observations of primary-source model listings; not authenticated API proof."""
from urllib.parse import urlencode, urlsplit
from datetime import datetime, timezone
from intelligence import extract_model_ids, evidence_key

FEED = "https://claudemon.com/feeds/changes.json"
LABS = ("openai", "anthropic", "google")
MAX_ITEMS = 50
ALLOWED_HOSTS = {"platform.openai.com", "developers.openai.com", "docs.anthropic.com",
                 "platform.claude.com", "ai.google.dev"}

def parse_claudemon_feed(document, *, now=None, max_age_days=14):
    if not isinstance(document, dict) or not isinstance(document.get("items"), list):
        raise ValueError("Invalid JSON Feed items")
    now = now or datetime.now(timezone.utc)
    if max_age_days <= 0:
        raise ValueError("max_age_days must be positive")
    found = {}
    items = sorted(document["items"], key=lambda item: item.get("date_published", "") if isinstance(item, dict) else "", reverse=True)[:MAX_ITEMS]
    for item in items:
        if not isinstance(item, dict):
            continue
        tags = item.get("tags", [])
        if not isinstance(tags, list) or "model.listing" not in tags or not any(lab in tags for lab in LABS):
            continue
        title, url = item.get("title"), item.get("url")
        if not isinstance(title, str) or not isinstance(url, str):
            continue
        parsed_url = urlsplit(url)
        if parsed_url.scheme != "https" or parsed_url.hostname not in ALLOWED_HOSTS or parsed_url.username or parsed_url.password:
            continue
        published = item.get("date_published")
        if not isinstance(published, str):
            continue
        try:
            date = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            continue
        if date.tzinfo is None or not 0 <= (now - date).total_seconds() <= max_age_days * 86400:
            continue
        if "/models/" not in parsed_url.path and "/model/" not in parsed_url.path:
            continue
        ids = extract_model_ids(title)
        path_model = parsed_url.path.rstrip("/").split("/")[-1].lower()
        for model in ids:
            if model.lower() != path_model:
                continue
            record = {"model": model, "source": "external_listing",
                      "provider": "claudemon", "reference": url,
                      "observation_url": "https://claudemon.com/",
                      "title": title[:180]}
            if isinstance(item.get("date_published"), str):
                record["published_at"] = item["date_published"][:40]
            found[evidence_key(record)] = record
    return list(found.values())

def collect_claudemon(fetch_json):
    found = {}
    failures = 0
    for lab in LABS:
        url = FEED + "?" + urlencode({"lab": lab, "kind": "model.listing"})
        try:
            data = fetch_json(url, {"User-Agent": "FrontierWatchAI/0.9",
                                    "Accept": "application/feed+json, application/json"})
            for entry in parse_claudemon_feed(data):
                found[evidence_key(entry)] = entry
        except Exception:
            failures += 1
    status = "failed" if failures == len(LABS) else "partial" if failures else "ok"
    return list(found.values()), {"status": status, "failed_labs": failures,
                                  "observations": len(found)}

def source_alerts(fresh, limit=5):
    records = [e for e in fresh if e.get("source") == "external_listing"]
    if not records:
        return []
    lines = ["FrontierWatch AI — EXTERNAL listing observation (not independently API verified)",
             "A third-party feed linked to a model documentation URL. Check original evidence."]
    for record in records[:limit]:
        lines.extend([record["model"], record["reference"]])
    if len(records) > limit:
        lines.append(f"+{len(records)-limit} additional observations in evidence history")
    return ["\n".join(lines)]
