"""Prompts for each strategy. Stable text comes first, so providers can cache it."""
import re

LABELS = ["claim", "policy_change", "cancellation", "billing", "complaint", "general_enquiry"]
CLAIM_TYPES = ["fire_or_lightning", "theft", "escape_of_water", "storm", "accidental_damage", "other"]
REFUSAL = "Not stated in the policy."

def sections(policy_md):
    parts = re.split(r"\n(?=## )", policy_md)
    return [p.strip() for p in parts if p.strip().startswith("## ")]

# ---------- Baseline: one strong model, full context, long instructions, step-by-step reasoning ----------
BASELINE_INTRO = ("You are a highly experienced insurance operations specialist working for a home insurer. "
                  "You are careful, thorough and accurate. Read the request below carefully. "
                  "Think step by step and explain your reasoning in detail before answering. "
                  "Then give the final answer on the last line, starting with FINAL:")

def baseline(task, policy_md):
    t = task["type"]
    if t == "classify":
        system = BASELINE_INTRO + f"\nClassify the customer message into exactly one of these categories: {', '.join(LABELS)}. The FINAL line must contain only the category."
    elif t == "extract":
        system = BASELINE_INTRO + ("\nExtract these fields from the claim message as JSON: policy_number (format MHI-123456), "
                  "incident_date (YYYY-MM-DD), claim_type (one of: " + ", ".join(CLAIM_TYPES) + "), estimated_amount (a number). "
                  "The FINAL line must contain only the JSON object.")
    else:
        system = BASELINE_INTRO + f"\nAnswer the customer's question using only the policy below. If the policy does not say, the FINAL line must be exactly: {REFUSAL}\n\nPOLICY:\n{policy_md}"
    return system, task["input"]

# ---------- Optimised: short, stable instructions; trimmed context; direct answers ----------
OPT = {
    "classify": f"Classify the customer message. Reply with one word from: {', '.join(LABELS)}.",
    "extract": ("Return only a JSON object with keys policy_number (MHI-123456 format), incident_date (YYYY-MM-DD), "
                "claim_type (one of: " + ", ".join(CLAIM_TYPES) + "), estimated_amount (number). No other text."),
    "answer": f"Answer in one or two sentences using only the policy extract. Quote the exact figures. If the extract does not say, reply exactly: {REFUSAL}",
}

def retrieve(question, policy_md, k=2):
    """Knowledge retrieval: keep only the policy sections most related to the question."""
    words = set(w for w in re.findall(r"[a-z]+", question.lower()) if len(w) > 3)
    synonyms = {"burgled": "theft", "burglary": "theft", "stolen": "theft", "away": "unoccupied", "travelling": "unoccupied",
                "pipe": "water", "flooded": "water", "stay": "accommodation", "cooling": "cancel", "refund": "cancel",
                "premium": "cancel", "police": "theft", "car": "vehicle"}
    words |= {synonyms[w] for w in list(words) if w in synonyms}
    scored = []
    for s in sections(policy_md):
        text = s.lower()
        scored.append((sum(text.count(w) for w in words), s))
    scored.sort(key=lambda x: -x[0])
    chosen = [s for score, s in scored[:k] if score > 0]
    return "\n\n".join(chosen) if chosen else "(No relevant section found.)"

def optimised(task, policy_md):
    t = task["type"]
    if t == "answer":
        return OPT["answer"], f"POLICY EXTRACT:\n{retrieve(task['input'], policy_md)}\n\nQUESTION: {task['input']}"
    return OPT[t], task["input"]

REFLECT = ("Check the draft answer against the source. Correct any mistake. Reply with the final answer only, in the same format as the draft.")

def final_line(text):
    """Take the answer after the last FINAL: marker, if present."""
    if "FINAL:" in text:
        return text.rsplit("FINAL:", 1)[1].strip()
    return text.strip()
