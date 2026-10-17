"""Evaluation: score each answer against the expected result, with checks a person can audit."""
import json, re
from .prompts import LABELS, CLAIM_TYPES, REFUSAL

def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m: return None
    try: return json.loads(m.group(0))
    except Exception: return None

def validate(task, text):
    """Guardrail: is the output in the required format? Returns an error message, or None if valid."""
    if task["type"] == "classify":
        return None if text.strip().lower().strip(".") in LABELS else f"Reply must be one of: {', '.join(LABELS)}."
    if task["type"] == "extract":
        d = parse_json(text)
        if d is None: return "Reply must be a valid JSON object."
        missing = [k for k in ["policy_number", "incident_date", "claim_type", "estimated_amount"] if k not in d]
        if missing: return f"Missing keys: {', '.join(missing)}."
        if d.get("claim_type") not in CLAIM_TYPES: return f"claim_type must be one of: {', '.join(CLAIM_TYPES)}."
        return None
    return None if text.strip() else "Reply was empty."

def _norm_amount(v):
    try: return float(str(v).replace(",", "").replace("SGD", "").replace("S$", "").strip())
    except Exception: return None

def score(task, text):
    """Returns a score from 0 to 1."""
    e, t = task["expected"], task["type"]
    if t == "classify":
        return 1.0 if text.strip().lower().strip(".") == e["label"] else 0.0
    if t == "extract":
        d = parse_json(text) or {}
        checks = [
            str(d.get("policy_number", "")).upper().replace(" ", "") == e["policy_number"],
            str(d.get("incident_date", "")) == e["incident_date"],
            d.get("claim_type") == e["claim_type"],
            _norm_amount(d.get("estimated_amount")) == float(e["estimated_amount"]),
        ]
        return sum(checks) / len(checks)
    low = text.lower().replace(",", "")
    if e.get("refusal"):
        return 1.0 if REFUSAL.lower().rstrip(".") in low else 0.0
    if REFUSAL.lower().rstrip(".") in low:
        return 0.0
    hits = [any(alt.lower().replace(",", "") in low for alt in group) for group in e["facts"]]
    return sum(hits) / len(hits)
