"""Provider-reported catalog metadata with an explicit public-field allowlist."""
import re
from datetime import datetime

IDENTIFIER = re.compile(r"^[^\s]{1,160}$")
OWNER = re.compile(r"^[a-zA-Z0-9._-]{1,80}$")
MIN_EPOCH = 946684800    # 2000-01-01
MAX_EPOCH = 4102444800   # 2100-01-01


def catalog_metadata(provider, models):
    """Keep *only* the provider's safe creation/owner fields, never raw objects.

    Dates are provider-reported properties, not the time this tracker observed
    an identifier. Their presence alone does not establish model availability.
    """
    if not isinstance(models, list):
        raise ValueError("Expected model list")
    recorded = {}
    for model in models:
        if not isinstance(model, dict):
            continue
        value = model.get("id") or model.get("name")
        if not isinstance(value, str):
            continue
        model_id = value.strip()
        if not IDENTIFIER.fullmatch(model_id):
            continue
        safe = {}
        if provider in ("openai", "openrouter"):
            created = model.get("created")
            if type(created) is int and MIN_EPOCH <= created <= MAX_EPOCH:
                safe["created"] = created
        if provider == "openai":
            owner = model.get("owned_by")
            if isinstance(owner, str) and OWNER.fullmatch(owner):
                safe["owned_by"] = owner
        if provider == "anthropic":
            created_at = model.get("created_at")
            if isinstance(created_at, str) and len(created_at) <= 40:
                try:
                    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except ValueError:
                    pass
                else:
                    if parsed.tzinfo is not None:
                        safe["created_at"] = created_at
        if safe:
            recorded[model_id] = safe
    return recorded
