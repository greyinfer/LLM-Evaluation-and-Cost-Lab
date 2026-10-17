"""Runs each strategy over the test set and records quality, tokens, cost and speed for every task."""
import json, re, time
from . import prompts
from .providers import call_with_retries
from .scoring import score, validate

def route(task):
    """Routing: send simple tasks to the cheaper model and complex ones to the stronger model.
    Rules only look at the task itself, never at its difficulty label, so routing accuracy can be measured."""
    text = task["input"]
    if task["type"] == "classify":
        complex_signals = ["waiting", "escalate", "and tell me", "and can", "weeks"]
        return "strong" if any(s in text.lower() for s in complex_signals) else "cheap"
    if task["type"] == "extract":
        messy = len(text) > 170 or "sorry" in text.lower() or "two things" in text.lower() or "roughly" in text.lower() or "k." in text
        return "strong" if messy else "cheap"
    multi_part = text.count(" and ") >= 1 or len(text) > 80 or "if i" in text.lower() or "am i covered" in text.lower()
    return "strong" if multi_part else "cheap"

class Run:
    def __init__(self, provider, models, policy_md, caps, wait, retries):
        self.p, self.models, self.policy, self.caps, self.wait, self.retries = provider, models, policy_md, caps, wait, retries
        self.cache = {}

    def _call(self, model, system, user, max_tokens=None, limit_thinking=False):
        return call_with_retries(lambda: self.p.generate(model, system, user, max_tokens, limit_thinking), self.retries, self.wait)

    def _row(self, task, strategy, text, calls, models_used, extra):
        r = {"id": task["id"], "type": task["type"], "difficulty": task["difficulty"], "strategy": strategy,
             "answer": text, "score": score(task, text), "models": models_used,
             "calls": len(calls), "input_tokens": sum(c.input_tokens for c in calls),
             "output_tokens": sum(c.output_tokens for c in calls), "cached_tokens": sum(c.cached_tokens for c in calls),
             "latency_s": round(sum(c.latency_s for c in calls), 3), "retries": sum(c.retries for c in calls),
             "token_usage_by_model": {}}
        for c in calls:
            u = r["token_usage_by_model"].setdefault(c.model, {"input": 0, "output": 0})
            u["input"] += c.input_tokens; u["output"] += c.output_tokens
        r.update(extra)
        return r

    def baseline(self, task):
        system, user = prompts.baseline(task, self.policy)
        c = self._call(self.models["strong"], system, user)
        return self._row(task, "baseline", prompts.final_line(c.text), [c], [c.model], {})

    def reflection(self, task):
        """Reflection: on hard tasks, a second pass reviews and corrects the first answer. Its extra cost is measured."""
        system, user = prompts.optimised(task, self.policy)
        m = self.models["strong"]
        first = self._call(m, system, user, self.caps[task["type"]])
        calls, text = [first], first.text.strip()
        if task["difficulty"] == "hard":
            review_user = f"SOURCE AND TASK:\n{user}\n\nDRAFT ANSWER:\n{text}"
            second = self._call(m, system + "\n" + prompts.REFLECT, review_user, self.caps[task["type"]])
            calls.append(second); text = second.text.strip()
        return self._row(task, "reflection", text, calls, [c.model for c in calls], {"reflected": task["difficulty"] == "hard"})

    def optimised(self, task):
        key = (task["type"], re.sub(r"\s+", " ", task["input"].strip().lower()))
        if key in self.cache:  # Response cache: identical requests reuse the stored answer at zero token cost
            return self._row(task, "optimised", self.cache[key], [], [], {"cache_hit": True, "routed_to": "cache"})
        tier = route(task)
        system, user = prompts.optimised(task, self.policy)
        cap = self.caps[task["type"]]
        calls, repaired, escalated = [], False, False
        c = self._call(self.models[tier], system, user, cap, limit_thinking=(tier == "cheap")); calls.append(c)
        text = c.text.strip(); err = validate(task, text)
        if err:  # Guardrail: one repair attempt, telling the model what was wrong
            repaired = True
            c = self._call(self.models[tier], system, f"{user}\n\nYour previous reply was invalid: {err} Reply again correctly.", cap, limit_thinking=(tier == "cheap"))
            calls.append(c); text = c.text.strip(); err = validate(task, text)
        if err and tier == "cheap":  # Fallback: escalate to the stronger model if the cheap one still fails
            escalated = True
            c = self._call(self.models["strong"], system, user, cap); calls.append(c); text = c.text.strip()
        self.cache[key] = text
        return self._row(task, "optimised", text, calls, [x.model for x in calls],
                         {"cache_hit": False, "routed_to": tier, "repaired": repaired, "escalated": escalated})

def run_all(tasks, strategies, provider, models, policy_md, caps, wait, retries, out_dir):
    run = Run(provider, models, policy_md, caps, wait, retries)
    rows = []
    for s in strategies:
        print(f"\nStrategy: {s}")
        fn = getattr(run, s)
        for t in tasks:
            try:
                r = fn(t)
            except Exception as e:  # keep going so one failure does not lose the whole run
                r = {"id": t["id"], "type": t["type"], "difficulty": t["difficulty"], "strategy": s, "answer": "",
                     "score": 0.0, "error": str(e)[:200], "calls": 0, "input_tokens": 0, "output_tokens": 0,
                     "cached_tokens": 0, "latency_s": 0, "retries": 0, "models": [], "token_usage_by_model": {}}
            rows.append(r)
            print(f"  {t['id']:<3} score {r['score']:.2f}  tokens {r['input_tokens'] + r['output_tokens']:>6}" + (f"  error: {r['error']}" if r.get("error") else ""))
        with open(out_dir / f"{s}.jsonl", "w") as f:
            for r in rows:
                if r["strategy"] == s: f.write(json.dumps(r) + "\n")
    return rows
