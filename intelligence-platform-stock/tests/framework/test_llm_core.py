"""
Framework tests: generic LLM core.

Verifies structured-output recovery and the OpenAI-compatible transport
engine work generically, using a fake SDK client (no network). Same
engine must serve Stock and HR prompts.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.intelligence.llm import LLMClient, extract_json  # noqa: E402


# ── extract_json ─────────────────────────────────────────────────

def test_extract_json_pure_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_markdown_fence():
    content = '```json\n{"summary": "ok"}\n```'
    assert extract_json(content) == {"summary": "ok"}


def test_extract_json_plain_fence():
    content = '```\n{"x": 2}\n```'
    assert extract_json(content) == {"x": 2}


def test_extract_json_prose_wrapped():
    content = 'Here is my analysis:\n{"bull_case": ["growth"]}\nHope that helps!'
    assert extract_json(content) == {"bull_case": ["growth"]}


def test_extract_json_empty_content():
    assert extract_json("") == {"raw_response": ""}
    assert extract_json(None) == {"raw_response": ""}


def test_extract_json_no_json_falls_back_to_raw():
    out = extract_json("no structure here")
    assert out == {"raw_response": "no structure here"}


def test_extract_json_non_dict_ignored():
    # A bare JSON array is not a dict → falls through to raw_response.
    assert extract_json('[1, 2]') == {"raw_response": "[1, 2]"}


# ── LLMClient ────────────────────────────────────────────────────

class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeUsage:
    def __init__(self, total):
        self.total_tokens = total


class _FakeCompletions:
    def __init__(self, content, usage_total=None):
        self._content = content
        self._usage = _FakeUsage(usage_total) if usage_total is not None else None
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs

        class _Resp:
            pass

        r = _Resp()
        r.choices = [_FakeChoice(self._content)]
        r.usage = self._usage
        return r


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeSDK:
    def __init__(self, completions):
        self.chat = _FakeChat(completions)


def _client_with(content, usage_total=None) -> tuple[LLMClient, _FakeCompletions]:
    client = LLMClient(api_key="test-key", model="test-model", temperature=0.3)
    completions = _FakeCompletions(content, usage_total)
    client._client = _FakeSDK(completions)  # inject fake transport
    return client, completions


def test_chat_json_parses_valid_response_with_tokens():
    client, comps = _client_with('{"summary": "fine"}', usage_total=123)

    async def run():
        return await client.chat_json("system prompt", "user message")

    result, tokens = asyncio.run(run())
    assert result == {"summary": "fine"}
    assert tokens == 123
    kwargs = comps.last_kwargs
    assert kwargs["model"] == "test-model"
    assert kwargs["temperature"] == 0.3
    assert kwargs["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in kwargs["messages"]] == ["system", "user"]


def test_chat_json_recovers_invalid_json():
    client, _ = _client_with(
        'Sure!\n```json\n{"insights": []}\n```', usage_total=10
    )

    async def run():
        return await client.chat_json("s", "u")

    result, tokens = asyncio.run(run())
    assert result == {"insights": []}
    assert tokens == 10


def test_chat_json_none_usage_yields_none_tokens():
    client, _ = _client_with('{"summary": "s"}', usage_total=None)

    async def run():
        return await client.chat_json("s", "u")

    result, tokens = asyncio.run(run())
    assert result == {"summary": "s"}
    assert tokens is None


def test_build_user_message_defaults_and_override():
    client = LLMClient(api_key="k", model="m")
    default_msg = client.build_user_message({"pe": 30})
    assert '"pe": 30' in default_msg
    assert client.build_user_message({"pe": 30}, user_query="custom") == "custom"


def test_build_meta_audit_block():
    client = LLMClient(
        api_key="k", model="gpt-x", provider="gemini",
        temperature=0.5, max_tokens=2048,
    )
    meta = client.build_meta(
        tokens_used=42,
        prompt_name="company_analysis",
        prompt_version="1.0",
        analysis_type="company",
    )
    assert meta["model"] == "gpt-x"
    assert meta["provider"] == "gemini"
    assert meta["tokens_used"] == 42
    assert meta["prompt_name"] == "company_analysis"
    assert meta["prompt_version"] == "1.0"
    assert meta["analysis_type"] == "company"
    assert meta["temperature"] == 0.5
    assert meta["max_tokens"] == 2048


def test_engine_is_domain_neutral():
    # Stock-style and HR-style payloads flow through identically.
    stock_client, _ = _client_with('{"investment_thesis": "..."}')
    hr_client, _ = _client_with('{"candidate_summary": "..."}')

    async def run():
        s = await stock_client.chat_json("stock prompt", "ctx")
        h = await hr_client.chat_json("hr prompt", "ctx")
        return s, h

    (s_res, _), (h_res, _) = asyncio.run(run())
    assert "investment_thesis" in s_res
    assert "candidate_summary" in h_res


# ── LLMClient transient-error retry ────────────────────────────────


class _FlakyCompletions:
    """Fails N times with the given exception factory, then succeeds."""

    def __init__(self, failures, exc_factory, content='{"summary": "recovered"}'):
        self.failures = failures
        self.exc_factory = exc_factory
        self.good = _FakeCompletions(content, 7)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc_factory()
        return await self.good.create(**kwargs)


def _overloaded_503(retry_after=None):
    """Build the exact 503 from production: 'high demand', status UNAVAILABLE."""
    import httpx
    import openai

    headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
    response = httpx.Response(
        503,
        request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
        headers=headers,
        json={"error": {"code": 503, "message": "This model is currently experiencing high demand.", "status": "UNAVAILABLE"}},
    )
    return openai.InternalServerError("Error code: 503", response=response, body=None)


def _auth_error():
    import httpx
    import openai

    response = httpx.Response(
        401,
        request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
        json={"error": {"message": "bad key"}},
    )
    return openai.AuthenticationError("Error code: 401", response=response, body=None)


def _daily_quota_429():
    """Gemini free-tier per-day quota 429, exactly as seen in production."""
    import httpx
    import openai

    response = httpx.Response(
        429,
        request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
        json={"error": {"code": 429, "message": "You exceeded your current quota", "status": "RESOURCE_EXHAUSTED"}},
    )
    return openai.RateLimitError(
        "Error code: 429 - You exceeded your current quota. "
        "Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests. "
        "quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier",
        response=response,
        body=None,
    )


def _retry_client(completions, max_attempts=3):
    from app.intelligence.llm.client import LLMClient as _Client

    client = _Client(
        api_key="test-key",
        model="test-model",
        max_attempts=max_attempts,
        retry_base_delay=0.01,
        retry_max_delay=0.02,
    )
    client._client = _FakeSDK(completions)  # inject fake transport
    return client


def test_classify_llm_error_transient_vs_permanent():
    from app.intelligence.llm.client import classify_llm_error

    # Production 503 with no Retry-After → transient, no hint.
    assert classify_llm_error(_overloaded_503()) == -1.0
    # Server-supplied hint is honored.
    assert classify_llm_error(_overloaded_503(retry_after=7)) == 7.0
    # Gemini free-tier per-DAY quota → fail over immediately, don't retry.
    assert classify_llm_error(_daily_quota_429()) == -2.0
    # Non-transient / non-provider errors are never retried.
    assert classify_llm_error(_auth_error()) is None
    assert classify_llm_error(ValueError("not a provider error")) is None


def test_daily_quota_fails_over_to_fallback_immediately():
    """Free-tier daily quota: one primary attempt, then the fallback —
    no minutes of futile backoff on a model that cannot succeed today."""
    from app.intelligence.llm.client import DAILY_QUOTA, classify_llm_error

    class _QuotaRoutingCompletions:
        def __init__(self):
            self.good = _FakeCompletions('{"summary": "from fallback"}', 7)
            self.calls = []

        async def create(self, model=None, **kwargs):
            self.calls.append(model)
            if model == "primary-model":
                raise _daily_quota_429()
            return await self.good.create(model=model, **kwargs)

    comps = _QuotaRoutingCompletions()
    client = _fallback_client(comps, max_attempts=6)

    def run():
        return client.chat_json("system", "user")

    result, _ = asyncio.run(run())
    assert result == {"summary": "from fallback"}
    # Exactly ONE primary attempt (no retry loop), then the backup.
    assert comps.calls == ["primary-model", "backup-model"]
    assert classify_llm_error(_daily_quota_429()) == DAILY_QUOTA


def test_chat_json_retries_transient_503_and_recovers():
    comps = _FlakyCompletions(failures=2, exc_factory=_overloaded_503)
    client = _retry_client(comps, max_attempts=3)

    def run():
        return client.chat_json("system", "user")

    result, tokens = asyncio.run(run())
    assert result == {"summary": "recovered"}
    assert tokens == 7
    assert comps.calls == 3  # failed twice, succeeded on the third attempt


def test_chat_json_gives_up_after_max_attempts():
    comps = _FlakyCompletions(failures=99, exc_factory=_overloaded_503)
    client = _retry_client(comps, max_attempts=3)

    def run():
        return client.chat_json("system", "user")

    try:
        asyncio.run(run())
        raised = None
    except Exception as exc:  # noqa: BLE001 — assert the SDK error propagates
        raised = exc
    assert raised is not None
    assert "503" in str(raised)
    assert comps.calls == 3  # exactly max_attempts, no more


def test_chat_json_does_not_retry_non_transient_errors():
    comps = _FlakyCompletions(failures=1, exc_factory=_auth_error)
    client = _retry_client(comps, max_attempts=3)

    def run():
        return client.chat_json("system", "user")

    try:
        asyncio.run(run())
        raised = None
    except Exception as exc:  # noqa: BLE001
        raised = exc
    assert raised is not None
    assert comps.calls == 1  # auth errors raise immediately — retrying can't help


class _ModelRoutingCompletions:
    """Fails 503 for the listed models, succeeds otherwise; records order."""

    def __init__(self, failing_models, content='{"summary": "from fallback"}'):
        self.failing_models = set(failing_models)
        self.good = _FakeCompletions(content, 7)
        self.calls = []

    async def create(self, model=None, **kwargs):
        self.calls.append(model)
        if model in self.failing_models:
            raise _overloaded_503()
        return await self.good.create(model=model, **kwargs)


def _fallback_client(completions, max_attempts=2):
    from app.intelligence.llm.client import LLMClient as _Client

    client = _Client(
        api_key="test-key",
        model="primary-model",
        fallback_model="backup-model",
        max_attempts=max_attempts,
        retry_base_delay=0.01,
        retry_max_delay=0.02,
    )
    client._client = _FakeSDK(completions)  # inject fake transport
    return client


def test_chat_json_falls_back_when_primary_model_overloaded():
    comps = _ModelRoutingCompletions(failing_models={"primary-model"})
    client = _fallback_client(comps, max_attempts=2)

    def run():
        return client.chat_json("system", "user")

    result, tokens = asyncio.run(run())
    assert result == {"summary": "from fallback"}
    assert tokens == 7
    # Primary tried exactly max_attempts times, then the backup succeeded.
    assert comps.calls == ["primary-model", "primary-model", "backup-model"]
    assert client.last_model_used == "backup-model"
    meta = client.build_meta(
        tokens_used=7, prompt_name="company_analysis",
        prompt_version="1.0", analysis_type="company",
    )
    assert meta["model"] == "backup-model"  # provenance survives fallback


def test_no_fallback_on_non_transient_errors():
    comps = _FlakyCompletions(failures=1, exc_factory=_auth_error)
    client = _fallback_client(comps, max_attempts=3)

    def run():
        return client.chat_json("system", "user")

    try:
        asyncio.run(run())
        raised = None
    except Exception as exc:  # noqa: BLE001
        raised = exc
    assert raised is not None
    assert comps.calls == 1  # auth errors raise immediately — no retries, no fallback


def test_exhausted_retries_without_fallback_raise():
    comps = _ModelRoutingCompletions(failing_models={"test-model"})
    client = _retry_client(comps, max_attempts=2)  # no fallback configured

    def run():
        return client.chat_json("system", "user")

    try:
        asyncio.run(run())
        raised = None
    except Exception as exc:  # noqa: BLE001
        raised = exc
    assert raised is not None
    assert "503" in str(raised)
    assert comps.calls == ["test-model", "test-model"]


def test_llm_service_passes_retry_settings_to_engine():
    """LLMService wires the domain retry settings into the framework engine."""
    from app.intelligence.llm.client import LLMClient as _Client
    from app.domains.stock.config import get_stock_config
    from app.domains.stock.scoring.llm import LLMService

    cfg = get_stock_config()
    service = LLMService(api_key="k", model="m", provider="test")
    engine = service._get_engine()
    assert isinstance(engine, _Client)
    assert engine.max_attempts == cfg.LLM_MAX_ATTEMPTS
    assert engine.retry_base_delay == cfg.LLM_RETRY_BASE_DELAY
    assert engine.retry_max_delay == cfg.LLM_RETRY_MAX_DELAY


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print("ALL PASS" if failures == 0 else f"{failures} FAILURE(S)")
    sys.exit(1 if failures else 0)
