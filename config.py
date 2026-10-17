"""Settings for the LLM Evaluation and Cost Lab. Edit these to use your own provider and models."""

# Which provider to use: "gemini", "anthropic" or "mock" (offline dry run, no real results)
PROVIDER = "gemini"

# A cheaper model for easy tasks and a stronger model for hard ones.
# Aliases are used where available, because model names change often.
MODELS = {
    "gemini":    {"cheap": "gemini-flash-lite-latest", "strong": "gemini-flash-latest"},
    "anthropic": {"cheap": "claude-haiku-5-5",         "strong": "claude-sonnet-5-5"},
    "mock":      {"cheap": "mock-cheap",               "strong": "mock-strong"},
}

# Prices in USD per million tokens, used to turn tokens into cost.
# Leave as None to report tokens only. Fill these in from your provider's official pricing page.
PRICES_PER_MILLION = {
    # "gemini-flash-lite-latest": {"input": None, "output": None},
    # "gemini-flash-latest":      {"input": None, "output": None},
}

# Free tiers have low request limits, so the lab waits between calls and retries when rate-limited.
SECONDS_BETWEEN_CALLS = {"gemini": 4.5, "anthropic": 0.5, "mock": 0.0}
MAX_RETRIES = 4

# Output caps used by the optimised strategy, per task type.
OUTPUT_CAPS = {"classify": 10, "extract": 120, "answer": 160}
