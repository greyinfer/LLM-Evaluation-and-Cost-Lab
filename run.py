"""Run the LLM Evaluation and Cost Lab.

Examples:
  python run.py                                   # uses the provider in config.py
  python run.py --provider mock                   # offline dry run, no key needed, not real results
  python run.py --strategies baseline optimised --limit 8
"""
import argparse, json, datetime, pathlib
import config
from lab.providers import get_provider
from lab.runner import run_all
from lab.report import build

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=config.PROVIDER, choices=["gemini", "anthropic", "mock"])
    ap.add_argument("--strategies", nargs="+", default=["baseline", "optimised", "reflection"], choices=["baseline", "optimised", "reflection"])
    ap.add_argument("--limit", type=int, default=0, help="run only the first N tasks")
    a = ap.parse_args()
    root = pathlib.Path(__file__).parent
    tasks = [json.loads(l) for l in (root / "data/tasks.jsonl").read_text().splitlines() if l.strip()]
    if a.limit: tasks = tasks[: a.limit]
    policy = (root / "data/policy.md").read_text()
    models = config.MODELS[a.provider]
    provider = get_provider(a.provider, tasks)
    run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ("-mock" if a.provider == "mock" else "")
    out = root / "results" / run_id; out.mkdir(parents=True, exist_ok=True)
    rows = run_all(tasks, a.strategies, provider, models, policy, config.OUTPUT_CAPS,
                   config.SECONDS_BETWEEN_CALLS[a.provider], config.MAX_RETRIES, out)
    report, summary = build(rows, tasks, config.PRICES_PER_MILLION, a.provider, models, run_id, a.provider == "mock")
    (out / "report.md").write_text(report); (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n" + report); print(f"Saved to {out}")

if __name__ == "__main__":
    main()
