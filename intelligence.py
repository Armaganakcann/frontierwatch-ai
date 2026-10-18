"""Conservative, evidence-aware model identifier utilities."""
import re

KNOWN_PREFIXES = ("gpt-", "gemini-", "claude-", "aurora-", "o1-", "o3-", "o4-")
MODEL_ID = re.compile(r"(?<![a-zA-Z0-9_])(?:gpt|gemini|claude|aurora|o1|o3|o4)-[a-zA-Z0-9][a-zA-Z0-9._-]{1,70}", re.I)
LEVELS = {"catalog": "catalog_observation", "sdk_patch": "official_code_signal",
          "sdk_commit": "official_commit_signal", "sdk_release": "official_release_note",
          "rumor": "unverified"}

def extract_model_ids(text):
    if not isinstance(text, str):
        return []
    return sorted({m.group(0).lower().rstrip("._-") for m in MODEL_ID.finditer(text)})

def evidence_level(source):
    return LEVELS.get(source, "unverified")

def evidence_key(item):
    return "|".join(str(item.get(k, "")) for k in ("source", "provider", "model", "reference"))

def new_evidence(entries, seen):
    known = set(seen)
    fresh = []
    for entry in entries:
        key = evidence_key(entry)
        if key not in known:
            fresh.append(entry)
            known.add(key)
    return fresh

def merge_evidence(existing, incoming, timestamp):
    """Append previously unseen evidence without overwriting first_seen."""
    merged = list(existing)
    seen = {evidence_key(item) for item in merged}
    fresh = []
    for item in incoming:
        if not isinstance(item, dict) or not all(item.get(k) for k in ("model", "source", "provider", "reference")):
            continue
        key = evidence_key(item)
        if key in seen:
            continue
        record = dict(item)
        record["first_seen"] = timestamp
        record["level"] = evidence_level(record["source"])
        merged.append(record)
        fresh.append(record)
        seen.add(key)
    return merged, fresh

def model_summary(entries):
    """Aggregate observations without inferring release status."""
    grouped = {}
    for entry in entries:
        model = entry.get("model")
        if not isinstance(model, str) or not model:
            continue
        item = grouped.setdefault(model, {"first_seen": entry.get("first_seen", ""),
                                          "sources": set(), "release_confirmed": False})
        first = entry.get("first_seen", "")
        if first and (not item["first_seen"] or first < item["first_seen"]):
            item["first_seen"] = first
        item["sources"].add((entry.get("source", ""), entry.get("provider", "")))
    return {model: {"first_seen": data["first_seen"],
                    "source_count": len(data["sources"]),
                    "sources": sorted(f"{kind}:{provider}" for kind, provider in data["sources"]),
                    "release_confirmed": False}
            for model, data in sorted(grouped.items())}
