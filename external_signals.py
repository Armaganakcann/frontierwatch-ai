"""Third-party observations of primary-source model listings; not authenticated API proof."""
from urllib.parse import urlencode
from intelligence import extract_model_ids, evidence_key

FEED = "https://claudemon.com/feeds/changes.json"
LABS = ("openai", "anthropic", "google")
MAX_ITEMS = 50

def parse_claudemon_feed(document):
    if not isinstance(document, dict) or not isinstance(document.get("items"), list):
        raise ValueError("Invalid JSON Feed items")
    if len(document["items"]) > MAX_ITEMS:
        raise ValueError("Unexpectedly large feed")
    found = {}
    for item in document["items"]:
        if not isinstance(item, dict):
            continue
        tags = item.get("tags", [])
        if not isinstance(tags, list) or "model.listing" not in tags:
            continue
        title, url = item.get("title"), item.get("url")
        if not isinstance(title, str) or not isinstance(url, str):
            continue
        if not url.startswith(("https://platform.openai.com/", "https://developers.openai.com/",
                               "https://docs.anthropic.com/", "https://platform.claude.com/",
                               "https://ai.google.dev/")):
            continue
        ids = extract_model_ids(title)
        for model in ids:
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
