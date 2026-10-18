"""Public Hacker News model-name references; never treat posts as official releases."""
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

from intelligence import extract_model_ids, evidence_key

SEARCH_TERMS = ("aurora", "OpenAI model API", "Claude preview", "Gemini preview")
SEARCH_ENDPOINT = "https://hn.algolia.com/api/v1/search_by_date"
VALID_HN_ID = re.compile(r"^[0-9]{1,20}$")


def parse_hn_hit(hit, *, now=None, max_age_hours=72):
    """Convert a recent HN story to model-ID mention records, not verified facts."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(hit, dict):
        return []
    story_id, title = hit.get("objectID"), hit.get("title")
    published = hit.get("created_at_i")
    if not isinstance(story_id, str) or not VALID_HN_ID.fullmatch(story_id):
        return []
    if not isinstance(title, str) or not title.strip() or not isinstance(published, int):
        return []
    seconds_ago = now.timestamp() - published
    if seconds_ago < 0 or seconds_ago > max_age_hours * 3600:
        return []
    # Do not scan arbitrary target URLs; only the visible story title/text.
    text = title + " " + str(hit.get("story_text") or "")[:4000]
    candidates = extract_model_ids(text)
    clean_title = "".join(ch if ch.isprintable() else " " for ch in title).strip()[:180]
    if not clean_title:
        return []
    reference = f"https://news.ycombinator.com/item?id={story_id}"
    observed = datetime.fromtimestamp(published, timezone.utc).isoformat()
    return [{"source": "community", "provider": "hackernews", "model": model,
             "reference": reference, "title": clean_title, "published_at": observed}
            for model in candidates]


def collect_community(fetch_json, *, now=None, lookback_hours=72, max_pages=2):
    """Search public HN stories, retaining partial-failure diagnostics.

    Uses per-query server timestamp filtering, with a bounded pagination budget.
    Result sets can be incomplete when a query exceeds that budget.
    """
    now = now or datetime.now(timezone.utc)
    start = int(now.timestamp() - lookback_hours * 3600)
    observations = {}
    failed = 0
    successes = 0
    truncated_queries = 0
    for query in SEARCH_TERMS:
        try:
            for page in range(max_pages):
                params = urlencode({
                    "query": query, "tags": "story",
                    "numericFilters": f"created_at_i>{start}",
                    "hitsPerPage": 60, "page": page
                })
                result = fetch_json(SEARCH_ENDPOINT + "?" + params,
                                    {"User-Agent": "FrontierWatchAI/0.8"})
                if not isinstance(result, dict) or not isinstance(result.get("hits"), list):
                    raise ValueError("Invalid community search response")
                count_pages = result.get("nbPages")
                if not isinstance(count_pages, int) or count_pages < 0:
                    raise ValueError("Invalid page count")
                for hit in result["hits"]:
                    for evidence in parse_hn_hit(hit, now=now, max_age_hours=lookback_hours):
                        observations[evidence_key(evidence)] = evidence
                if page + 1 >= count_pages:
                    break
            else:
                truncated_queries += 1
            successes += 1
        except Exception:
            failed += 1
    status = "failed" if not successes else ("partial" if failed or truncated_queries else "ok")
    health = {"status": status, "query_count": len(SEARCH_TERMS),
              "failed_queries": failed, "truncated_queries": truncated_queries,
              "candidate_observations": len(observations), "initialized": successes > 0}
    return sorted(observations.values(), key=evidence_key), health


def community_alerts(fresh_entries, limit=4):
    """Produce one explicitly unverified alert per scan with a bounded excerpt."""
    entries = [x for x in fresh_entries if x.get("source") == "community"]
    if not entries or limit <= 0:
        return []
    lines = [f"FrontierWatch AI — UNVERIFIED public model-name mentions ({min(len(entries), limit)} of {len(entries)})",
             "Posts are NOT API verification, an official announcement, or proof of availability."]
    for entry in entries[:limit]:
        lines.append(f"{entry['model']}: {entry.get('title', '')[:160]}")
        lines.append(entry["reference"])
    return ["\n".join(lines)]
