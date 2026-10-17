"""One small interface for every model provider, so anyone can plug in their own API key."""
import os, time, random, re, json
from dataclasses import dataclass, field

@dataclass
class Reply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    model: str = ""
    latency_s: float = 0.0
    retries: int = 0

class RateLimited(Exception):
    pass

def call_with_retries(fn, max_retries, wait_between):
    """Exception handling and recovery: retry rate limits and transient errors with exponential backoff."""
    attempt = 0
    while True:
        try:
            time.sleep(wait_between)
            reply = fn()
            reply.retries = attempt
            return reply
        except Exception as e:  # noqa: BLE001 - providers raise different error types
            msg = str(e).lower()
            transient = any(k in msg for k in ["429", "rate", "quota", "resource_exhausted", "overloaded", "timeout", "503", "500"])
            if not transient or attempt >= max_retries:
                raise
            delay = min(60, (2 ** attempt) * 5) + random.uniform(0, 1)
            print(f"  Rate-limited or busy, waiting {delay:.0f}s before retry {attempt + 1}/{max_retries}")
            time.sleep(delay)
            attempt += 1

class GeminiProvider:
    name = "gemini"
    def __init__(self):
        from google import genai
        from google.genai import types
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise SystemExit("Set GEMINI_API_KEY first. Get a free key at aistudio.google.com.")
        self.client, self.types = genai.Client(api_key=key), types

    def generate(self, model, system, user, max_tokens=None, limit_thinking=False):
        t0 = time.time()
        kwargs = dict(system_instruction=system, temperature=0)
        if max_tokens: kwargs["max_output_tokens"] = max_tokens
        if limit_thinking:
            try:
                kwargs["thinking_config"] = self.types.ThinkingConfig(thinking_budget=0)
            except Exception:
                pass
        try:
            r = self.client.models.generate_content(model=model, contents=user, config=self.types.GenerateContentConfig(**kwargs))
        except Exception as e:
            if limit_thinking and "thinking" in str(e).lower():
                kwargs.pop("thinking_config", None)
                r = self.client.models.generate_content(model=model, contents=user, config=self.types.GenerateContentConfig(**kwargs))
            else:
                raise
        u = r.usage_metadata
        out = (getattr(u, "candidates_token_count", 0) or 0) + (getattr(u, "thoughts_token_count", 0) or 0)
        return Reply(text=r.text or "", input_tokens=getattr(u, "prompt_token_count", 0) or 0, output_tokens=out,
                     cached_tokens=getattr(u, "cached_content_token_count", 0) or 0, model=model, latency_s=time.time() - t0)

class AnthropicProvider:
    name = "anthropic"
    def __init__(self):
        import anthropic
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("Set ANTHROPIC_API_KEY first.")
        self.client = anthropic.Anthropic()

    def generate(self, model, system, user, max_tokens=None, limit_thinking=False):
        t0 = time.time()
        # Prompt caching: the stable system prompt is marked cacheable, so repeated calls reuse it.
        r = self.client.messages.create(model=model, max_tokens=max_tokens or 1024, temperature=0,
                                        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                                        messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        u = r.usage
        cached = (getattr(u, "cache_read_input_tokens", 0) or 0)
        return Reply(text=text, input_tokens=u.input_tokens + cached + (getattr(u, "cache_creation_input_tokens", 0) or 0),
                     output_tokens=u.output_tokens, cached_tokens=cached, model=model, latency_s=time.time() - t0)

class MockProvider:
    """Offline dry run. Fakes answers so the pipeline can be tested without a key. Never report these results."""
    name = "mock"
    def __init__(self, tasks_by_input=None):
        self.tasks_by_input = tasks_by_input or {}
    def generate(self, model, system, user, max_tokens=None, limit_thinking=False):
        task = next((t for k, t in self.tasks_by_input.items() if k in user), None)
        text = "Not stated in the policy."
        if task:
            e = task["expected"]
            if task["type"] == "classify": text = e["label"]
            elif task["type"] == "extract": text = json.dumps(e)
            elif e.get("refusal"): text = "Not stated in the policy."
            else: text = "Based on the policy: " + "; ".join(f[0] for f in e["facts"]) + "."
        if model.endswith("cheap") and task and task["difficulty"] == "hard" and task["type"] == "extract":
            text = text.replace('"', "'")  # simulate a cheap model breaking the JSON format on hard tasks
        words = len(re.findall(r"\S+", system + " " + user))
        out = max(3, len(text.split())) + (80 if "step by step" in system.lower() else 0)
        if max_tokens: out = min(out, max_tokens)
        return Reply(text=text, input_tokens=int(words * 1.3), output_tokens=int(out * 1.3), model=model, latency_s=0.01)

def get_provider(name, tasks=None):
    if name == "gemini": return GeminiProvider()
    if name == "anthropic": return AnthropicProvider()
    if name == "mock": return MockProvider({t["input"]: t for t in (tasks or [])})
    raise SystemExit(f"Unknown provider: {name}")
