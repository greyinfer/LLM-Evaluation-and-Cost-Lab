"""Builds a Markdown report comparing strategies on quality, tokens, cost and speed."""
from collections import defaultdict
from .runner import route

def cost_of(row, prices):
    total, known = 0.0, True
    for model, u in row.get("token_usage_by_model", {}).items():
        p = prices.get(model)
        if not p or p.get("input") is None or p.get("output") is None:
            known = known and (u["input"] + u["output"] == 0); continue
        total += u["input"] / 1e6 * p["input"] + u["output"] / 1e6 * p["output"]
    return total if known else None

def summarise(rows, prices):
    by = defaultdict(list)
    for r in rows: by[r["strategy"]].append(r)
    out = {}
    for s, rs in by.items():
        n = len(rs); costs = [cost_of(r, prices) for r in rs]
        out[s] = {"tasks": n, "quality": sum(r["score"] for r in rs) / n, "pass_rate": sum(r["score"] >= 0.999 for r in rs) / n,
                  "calls": sum(r["calls"] for r in rs), "input_tokens": sum(r["input_tokens"] for r in rs),
                  "output_tokens": sum(r["output_tokens"] for r in rs), "cached_tokens": sum(r["cached_tokens"] for r in rs),
                  "tokens_per_task": sum(r["input_tokens"] + r["output_tokens"] for r in rs) / n,
                  "cost": None if any(c is None for c in costs) else sum(costs),
                  "avg_latency": sum(r["latency_s"] for r in rs) / n,
                  "errors": sum(1 for r in rs if r.get("error")),
                  "by_type": {t: sum(r["score"] for r in rs if r["type"] == t) / max(1, sum(1 for r in rs if r["type"] == t)) for t in ["classify", "extract", "answer"]}}
    return out

def pct(a, b):
    return f"{(a - b) / b * 100:+.0f}%" if b else "n/a"

def build(rows, tasks, prices, provider, models, run_id, mock):
    S = summarise(rows, prices)
    L = []
    if mock:
        L += ["> **MOCK RUN. These are not real results.** They come from the offline test provider and only prove the pipeline works.", ""]
    L += [f"# Results: run {run_id}", "", f"Provider: **{provider}**. Cheap model: `{models['cheap']}`. Strong model: `{models['strong']}`. Tasks: {len(tasks)}.", "",
          "| Strategy | Quality | Pass rate | Calls | Input tokens | Output tokens | Cached tokens | Tokens per task | Cost (USD) | Avg latency (s) |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for s, v in S.items():
        cost = "set prices" if v["cost"] is None else f"{v['cost']:.4f}"
        L.append(f"| {s} | {v['quality']:.2f} | {v['pass_rate']:.0%} | {v['calls']} | {v['input_tokens']:,} | {v['output_tokens']:,} | {v['cached_tokens']:,} | {v['tokens_per_task']:.0f} | {cost} | {v['avg_latency']:.2f} |")
    if "baseline" in S and "optimised" in S:
        b, o = S["baseline"], S["optimised"]
        L += ["", "## Optimised compared with baseline", "",
              f"- Tokens per task: {pct(o['tokens_per_task'], b['tokens_per_task'])}",
              f"- Quality: {o['quality'] - b['quality']:+.2f} (on a 0 to 1 scale)",
              f"- Cost: " + (pct(o['cost'], b['cost']) if o['cost'] is not None and b['cost'] else "set prices in config.py to calculate"),
              f"- Average latency: {pct(o['avg_latency'], b['avg_latency'])}"]
    if "reflection" in S:
        rf = S["reflection"]
        L += ["", "## Reflection experiment", "", f"Reflection reviews hard answers a second time. Quality {rf['quality']:.2f} at {rf['tokens_per_task']:.0f} tokens per task. Compare with the optimised row to judge whether the extra cost buys enough quality."]
    opt = [r for r in rows if r["strategy"] == "optimised"]
    if opt:
        routed = [r for r in opt if r.get("routed_to") in ("cheap", "strong")]
        agree = sum((r["routed_to"] == "strong") == (r["difficulty"] == "hard") for r in routed)
        L += ["", "## What the optimisations did", "",
              f"- Routing: {sum(r.get('routed_to') == 'cheap' for r in opt)} tasks went to the cheap model, {sum(r.get('routed_to') == 'strong' for r in opt)} to the strong model. The router agreed with the difficulty labels on {agree} of {len(routed)} tasks.",
              f"- Response cache: {sum(1 for r in opt if r.get('cache_hit'))} repeated requests answered at zero token cost.",
              f"- Guardrail repairs: {sum(1 for r in opt if r.get('repaired'))}. Escalations to the strong model: {sum(1 for r in opt if r.get('escalated'))}."]
    L += ["", "## Quality by task type", "", "| Strategy | Classify | Extract | Answer |", "|---|---|---|---|"]
    for s, v in S.items():
        bt = v["by_type"]; L.append(f"| {s} | {bt['classify']:.2f} | {bt['extract']:.2f} | {bt['answer']:.2f} |")
    errs = sum(v["errors"] for v in S.values())
    if errs: L += ["", f"Note: {errs} task runs failed with errors and scored 0. See the run files for details."]
    return "\n".join(L) + "\n", S
