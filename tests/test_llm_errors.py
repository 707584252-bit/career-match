"""DeepSeek 客户端的错误处理测试（全部拦截网络层，不发真实请求）。

重点覆盖「Key 是对的但账户没钱」这一类容易被误判的失败：
用户看到 HTTP 402 时，第一反应通常是去重建 Key，而这恰恰是无效操作。
客户端的职责是把服务端那句 ``Insufficient Balance`` 翻译成明确的下一步。
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from career_compass.cli import _summarize_balance, main
from career_compass.llm import (
    HTTP_HINTS,
    DeepSeekClient,
    InsufficientBalanceError,
    LLMError,
    MissingAPIKeyError,
    _format_http_error,
)


def _http_error(code: int, body: dict | str, reason: str = "") -> urllib.error.HTTPError:
    """构造一个带响应体的 HTTPError，用来模拟服务端返回。"""
    payload = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    return urllib.error.HTTPError(
        "https://api.deepseek.com/chat/completions",
        code,
        reason or "Error",
        {},  # type: ignore[arg-type]
        io.BytesIO(payload.encode("utf-8")),
    )


@pytest.fixture
def no_sleep(monkeypatch):
    """重试退避不必真的等待，否则测试要跑好几秒。"""
    monkeypatch.setattr("time.sleep", lambda _seconds: None)


# ---------------------------------------------------------------------------
# 错误信息本身的可读性
# ---------------------------------------------------------------------------


def test_balance_error_message_tells_user_what_to_do():
    msg = _format_http_error(402, '{"error": {"message": "Insufficient Balance"}}', "Payment Required")
    assert "HTTP 402" in msg
    assert "余额不足" in msg
    assert "top_up" in msg, "必须给出充值入口"
    # 服务端原文要保留，否则线上排查时无从对照
    assert "Insufficient Balance" in msg


def test_auth_error_message_mentions_recreating_key():
    msg = _format_http_error(401, '{"error": {"message": "Authentication Fails"}}', "Unauthorized")
    assert "HTTP 401" in msg
    assert "api_keys" in msg


def test_unknown_status_code_still_reports_code():
    msg = _format_http_error(418, "", "")
    assert "HTTP 418" in msg
    assert "\n" not in msg, "没有附加信息时不应产生多余空行"


@pytest.mark.parametrize("code", [401, 402, 429, 500, 503])
def test_common_codes_have_hints(code):
    assert code in HTTP_HINTS


# ---------------------------------------------------------------------------
# 状态码 → 异常类型的映射
# ---------------------------------------------------------------------------


def test_402_raises_dedicated_balance_error_and_does_not_retry(monkeypatch, no_sleep):
    client = DeepSeekClient(api_key="sk-test", max_retries=2)
    calls: list[int] = []

    def fake_urlopen(req, timeout=None, context=None):
        calls.append(1)
        raise _http_error(402, {"error": {"message": "Insufficient Balance"}}, "Payment Required")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(InsufficientBalanceError) as ei:
        client.chat([{"role": "user", "content": "hi"}])

    assert "余额不足" in str(ei.value)
    assert len(calls) == 1, "余额不足重试多少次都是同样的结果，不应重试"


def test_balance_error_is_a_llm_error():
    """既有的 except LLMError 兜底逻辑必须仍然能捕获它。"""
    assert issubclass(InsufficientBalanceError, LLMError)


def test_401_is_plain_llm_error_not_balance_error(monkeypatch, no_sleep):
    client = DeepSeekClient(api_key="sk-test", max_retries=2)
    calls: list[int] = []

    def fake_urlopen(req, timeout=None, context=None):
        calls.append(1)
        raise _http_error(401, {"error": {"message": "Authentication Fails"}}, "Unauthorized")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(LLMError) as ei:
        client.chat([{"role": "user", "content": "hi"}])

    assert not isinstance(ei.value, InsufficientBalanceError)
    assert len(calls) == 1, "鉴权失败重试无意义"


def test_429_is_retried(monkeypatch, no_sleep):
    """限流是暂时性的，应该重试——这与其余 4xx 的处理方式相反。"""
    client = DeepSeekClient(api_key="sk-test", max_retries=2)
    calls: list[int] = []

    def fake_urlopen(req, timeout=None, context=None):
        calls.append(1)
        raise _http_error(429, {"error": {"message": "Rate limit"}}, "Too Many Requests")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "hi"}])

    assert len(calls) == 3, "1 次原始请求 + 2 次重试"


def test_5xx_is_retried_then_raises(monkeypatch, no_sleep):
    client = DeepSeekClient(api_key="sk-test", max_retries=2)
    calls: list[int] = []

    def fake_urlopen(req, timeout=None, context=None):
        calls.append(1)
        raise _http_error(503, "service unavailable", "Service Unavailable")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(LLMError) as ei:
        client.chat([{"role": "user", "content": "hi"}])

    assert len(calls) == 3
    assert "503" in str(ei.value)


def test_transient_failure_then_success(monkeypatch, no_sleep):
    """前两次失败、第三次成功时应正常返回内容，而不是把异常抛给用户。"""
    client = DeepSeekClient(api_key="sk-test", max_retries=2)
    calls: list[int] = []

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "通了"}}]}).encode("utf-8")

    def fake_urlopen(req, timeout=None, context=None):
        calls.append(1)
        if len(calls) < 3:
            raise _http_error(503, "overloaded", "Service Unavailable")
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert client.chat([{"role": "user", "content": "hi"}]) == "通了"
    assert len(calls) == 3


# ---------------------------------------------------------------------------
# 余额查询
# ---------------------------------------------------------------------------


def test_balance_returns_parsed_payload(monkeypatch):
    client = DeepSeekClient(api_key="sk-test")
    payload = {
        "is_available": False,
        "balance_infos": [
            {
                "currency": "CNY",
                "total_balance": "0.00",
                "granted_balance": "0.00",
                "topped_up_balance": "0.00",
            }
        ],
    }

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None, context=None: FakeResp())

    assert client.balance() == payload


def test_balance_requires_key(monkeypatch, tmp_path):
    # 必须同时隔离两个来源：环境变量，以及项目根目录的 .env。
    # 空字符串在 __init__ 里是假值，会继续回退到环境变量，所以只传 api_key="" 拦不住。
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(MissingAPIKeyError):
        DeepSeekClient(api_key="").balance()


def test_summarize_balance_is_readable():
    text = _summarize_balance(
        {
            "is_available": False,
            "balance_infos": [
                {
                    "currency": "CNY",
                    "total_balance": "0.00",
                    "topped_up_balance": "0.00",
                    "granted_balance": "0.00",
                }
            ],
        }
    )
    assert "CNY" in text and "0.00" in text


def test_summarize_balance_handles_empty_payload():
    assert "未返回" in _summarize_balance({})
    assert "未返回" in _summarize_balance({"balance_infos": []})


# ---------------------------------------------------------------------------
# 命令行表现
# ---------------------------------------------------------------------------


def test_cli_llm_test_surfaces_balance_when_out_of_credit(monkeypatch, tmp_path, capsys):
    """这是本次真实的用户场景：Key 正确、网络正常，但余额为 0。"""
    monkeypatch.chdir(tmp_path)  # 避开项目里的 .env
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    def fake_test_connection(self):
        raise InsufficientBalanceError(
            _format_http_error(402, '{"error": {"message": "Insufficient Balance"}}', "Payment Required")
        )

    monkeypatch.setattr(DeepSeekClient, "test_connection", fake_test_connection)
    monkeypatch.setattr(
        DeepSeekClient,
        "balance",
        lambda self: {
            "is_available": False,
            "balance_infos": [
                {
                    "currency": "CNY",
                    "total_balance": "0.00",
                    "topped_up_balance": "0.00",
                    "granted_balance": "0.00",
                }
            ],
        },
    )

    assert main(["llm-test"]) == 1
    out = capsys.readouterr().out
    assert "余额不足" in out
    assert "CNY" in out and "0.00" in out, "应把余额直接摆出来"
    assert "不代表 Key 有问题" in out, "要明确打消「Key 坏了」的误判"


def test_cli_llm_test_still_reports_other_failures_plainly(monkeypatch, tmp_path, capsys):
    """非余额类失败不应触发余额查询这条支路。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    def boom(self):
        raise LLMError("网络请求失败：连接超时")

    monkeypatch.setattr(DeepSeekClient, "test_connection", boom)

    def should_not_be_called(self):  # pragma: no cover - 被调用即测试失败
        raise AssertionError("非余额错误不应查询余额")

    monkeypatch.setattr(DeepSeekClient, "balance", should_not_be_called)

    assert main(["llm-test"]) == 1
    out = capsys.readouterr().out
    assert "连接超时" in out
    assert "余额" not in out
