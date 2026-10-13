"""DeepSeek API 客户端（纯标准库实现，不需要安装任何第三方包）。

设计目标：让「接入大模型」这一步尽可能简单——
只要设置一个环境变量 ``DEEPSEEK_API_KEY``，就可以把规则引擎生成的
结构化结论交给大模型润色成一份个性化叙述型报告。

DeepSeek 的接口与 OpenAI / Anthropic Chat Completions 兼容，因此本客户端
同样可以直接指向任何 OpenAI 兼容端点（``base_url`` 可配置）。

当前模型（以官方文档为准，价格与模型名可能变动）
------------------------------------------------
===========================  ==================  ==================
模型名                        底层版本             适用场景
===========================  ==================  ==================
``deepseek-flash``（默认）    DeepSeek-V4.1-Flash  通用对话、写作、抽取
``deepseek-v4-pro``          DeepSeek-V4-Pro      最强能力，成本更高
===========================  ==================  ==================

两者上下文均为 1M，最大输出 384K。思考模式（thinking）**默认开启**，
本项目在生成报告时默认**关闭思考模式**——写报告属于表达类任务而非推理类任务，
开思考只会更慢更贵，且思考模式下 ``temperature`` 会被忽略。

最小用法::

    from career_compass.llm import DeepSeekClient
    client = DeepSeekClient()                 # 自动读 DEEPSEEK_API_KEY / .env
    print(client.chat([{"role": "user", "content": "你好"}]))

命令行自检::

    career-compass llm-test
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from pathlib import Path

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"

#: 可选模型（仅供 CLI 下拉提示使用，不强制校验）
KNOWN_MODELS = ("deepseek-flash", "deepseek-v4-pro")

#: 思考强度合法取值
REASONING_EFFORTS = ("low", "high", "max")

#: 从环境变量读取 API Key 时使用的变量名
API_KEY_ENV = "DEEPSEEK_API_KEY"


class LLMError(RuntimeError):
    """调用大模型失败。"""


class MissingAPIKeyError(LLMError):
    """未配置 API Key。"""


# ---------------------------------------------------------------------------
# .env 支持（极简实现，避免引入 python-dotenv）
# ---------------------------------------------------------------------------


def load_dotenv(path: str | None = None, override: bool = False) -> dict[str, str]:
    """从 ``.env`` 文件读取键值对并写入 ``os.environ``。

    规则：忽略空行与 ``#`` 开头的注释；支持 ``KEY=VALUE``；值两侧的引号会被去掉。
    已存在的环境变量默认不覆盖（``override=True`` 时覆盖）。

    Returns:
        本次实际读到的键值对。
    """
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    else:
        here = Path.cwd()
        candidates.extend(p / ".env" for p in [here, *here.parents])

    for c in candidates:
        if not c.is_file():
            continue
        found: dict[str, str] = {}
        for raw_line in c.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if override or key not in os.environ:
                os.environ[key] = value
            found[key] = value
        return found
    return {}


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


class DeepSeekClient:
    """极简的 DeepSeek / OpenAI 兼容客户端。

    Args:
        api_key: 密钥。缺省时依次尝试 ``api_key`` 参数 → 环境变量 → ``.env``。
        base_url: API 根地址，默认 ``https://api.deepseek.com``。
            若你的代理要求 ``/v1`` 前缀，可传入 ``https://api.deepseek.com/v1``。
        model: 模型名。``deepseek-chat``（通用对话）或 ``deepseek-reasoner``（深度推理）。
        timeout: 单次请求超时秒数。
        max_retries: 失败重试次数（指数退避）。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        load_dotenv()
        self.api_key = api_key or os.environ.get(API_KEY_ENV, "").strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    # -- 基础能力 ---------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """是否已配置可用的 API Key。"""
        return bool(self.api_key)

    def _require_key(self) -> None:
        if not self.enabled:
            raise MissingAPIKeyError(
                f"未找到 API Key。请设置环境变量 {API_KEY_ENV}，"
                "或在项目根目录创建 .env 文件写入 "
                f"{API_KEY_ENV}=sk-xxxxxxxx。详见 docs/DEEPSEEK.md。"
            )

    def _post(self, payload: dict) -> dict:
        self._require_key()
        url = f"{self.base_url}/chat/completions"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "career-compass/1.0 (+https://github.com/)",
            },
        )
        ctx = ssl.create_default_context()
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", errors="replace")[:500]
                except Exception:  # pragma: no cover - 兜底
                    pass
                # 4xx 通常是参数或鉴权问题，重试无意义
                if 400 <= e.code < 500 and e.code != 429:
                    raise LLMError(f"DeepSeek 返回 HTTP {e.code}：{detail or e.reason}") from e
                last_err = LLMError(f"DeepSeek 返回 HTTP {e.code}：{detail or e.reason}")
            except (urllib.error.URLError, TimeoutError, ssl.SSLError) as e:
                last_err = LLMError(f"网络请求失败：{e}")
            if attempt < self.max_retries:
                time.sleep(1.5 * (2**attempt))
        raise last_err or LLMError("调用 DeepSeek 失败，原因未知。")

    # -- 高层接口 ---------------------------------------------------------

    def chat(
        self,
        messages: Iterable[dict[str, str]],
        temperature: float = 1.0,
        max_tokens: int = 2600,
        model: str | None = None,
        thinking: bool = False,
        reasoning_effort: str | None = None,
    ) -> str:
        """执行一次对话补全，返回纯文本内容。

        Args:
            messages: 形如 ``[{"role": "system"|"user"|"assistant", "content": "..."}]``。
            temperature: 采样温度。DeepSeek 官方建议：代码/数学 0.0，
                数据抽取/分析 1.0，通用对话 1.3，翻译 1.3，创意写作 1.5。
                **注意：思考模式下该参数会被忽略（不会报错，但不生效）。**
            max_tokens: 最大输出长度。
            model: 覆盖实例上的默认模型。
            thinking: 是否开启思考模式。官方默认开启；本项目默认关闭，
                因为写报告属于表达型任务，开思考只增加延迟与成本。
            reasoning_effort: 思考强度，``low`` / ``high`` / ``max``。
                仅在 ``thinking=True`` 时有意义，缺省时由服务端决定（默认 high）。
        """
        payload: dict[str, object] = {
            "model": model or self.model,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "stream": False,
            "thinking": {"type": "enabled" if thinking else "disabled"},
        }
        if not thinking:
            payload["temperature"] = temperature
        if thinking and reasoning_effort:
            if reasoning_effort not in REASONING_EFFORTS:
                raise ValueError(
                    f"reasoning_effort 只能是 {REASONING_EFFORTS} 之一，收到 {reasoning_effort!r}"
                )
            payload["reasoning_effort"] = reasoning_effort

        data = self._post(payload)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:  # pragma: no cover - 兜底
            raise LLMError(f"无法解析 DeepSeek 返回内容：{json.dumps(data, ensure_ascii=False)[:500]}") from e

    def chat_detailed(
        self,
        messages: Iterable[dict[str, str]],
        temperature: float = 1.0,
        max_tokens: int = 2600,
        model: str | None = None,
        thinking: bool = False,
        reasoning_effort: str | None = None,
    ) -> dict[str, object]:
        """与 :meth:`chat` 相同，但同时返回思维链与用量统计。

        Returns:
            ``{"content": str, "reasoning_content": str, "usage": dict, "model": str}``
        """
        payload: dict[str, object] = {
            "model": model or self.model,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "stream": False,
            "thinking": {"type": "enabled" if thinking else "disabled"},
        }
        if not thinking:
            payload["temperature"] = temperature
        if thinking and reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort

        data = self._post(payload)
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:  # pragma: no cover - 兜底
            raise LLMError(f"无法解析 DeepSeek 返回内容：{json.dumps(data, ensure_ascii=False)[:500]}") from e
        return {
            "content": msg.get("content") or "",
            "reasoning_content": msg.get("reasoning_content") or "",
            "usage": data.get("usage", {}),
            "model": data.get("model", payload["model"]),
        }

    def test_connection(self) -> str:
        """发一条最小请求验证连通性与鉴权。"""
        return self.chat(
            [{"role": "user", "content": "只回复两个字：连通"}],
            temperature=0.0,
            max_tokens=16,
        )


# ---------------------------------------------------------------------------
# 面向本项目的报告生成
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一位资深的职业发展咨询顾问，兼具职业心理学与人才测评背景。

你会收到一份由规则引擎计算出的结构化测评结果，包含：
- 用户在学术能力、技能特长、个人特质、兴趣四大维度下 21 个子维度的得分
- 霍兰德三字代码
- 数据质量指标（完成率、作答一致性）
- 加权算法给出的职业推荐列表及匹配度、优势、差距

请基于这些数据，写一份中文个性化解读报告。硬性要求：

1. 必须忠实于给定数据，不得编造数据中没有的信息，不得发明用户未提及的经历。
2. 不要复述分数表格，要解释分数背后的含义与它们之间的关联。
   （例如：为什么「研究型兴趣高 + 外向性低」的组合指向某些岗位，而不是另一些。）
3. 明确指出数据质量风险：若一致性偏低或完成率不足，必须提示结论仅供参考。
4. 给出 3 条可在一周内开始执行的具体行动建议，要具体到动作，不要空话。
5. 语气专业、平实、不奉承、不制造焦虑。对「热门职业」保持中立。
6. 结尾必须包含一句免责声明：本报告基于自评问卷与规则模型生成，不构成职业决策或投资建议。
7. 使用 Markdown 小标题组织内容，总长度控制在 900~1400 字。
"""


def build_user_prompt(payload: dict) -> str:
    """把结构化测评结果序列化为提示词正文。"""
    return (
        "以下是我的职业能力测评结果（JSON），请据此生成个性化解读报告。\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )


def generate_narrative(
    payload: dict,
    client: DeepSeekClient | None = None,
    model: str | None = None,
    temperature: float = 1.0,
    thinking: bool = False,
    reasoning_effort: str | None = None,
) -> str:
    """把结构化测评结果交给 DeepSeek，返回叙述型报告（Markdown）。

    Args:
        payload: 由 ``cli`` 组装的结构化结果字典。
        client: 可复用已有客户端；缺省时新建。
        model: 覆盖模型名，例如 ``deepseek-v4-pro``。
        temperature: 采样温度。默认 1.0（官方推荐的「数据抽取/分析」档位），
            偏向忠实于给定数据而非自由发挥。想要更生动的文风可调到 1.3。
        thinking: 是否开启思考模式。默认关闭。
        reasoning_effort: 思考强度 ``low`` / ``high`` / ``max``（仅思考模式有效）。

    Raises:
        MissingAPIKeyError: 未配置 API Key。
        LLMError: 调用失败。
    """
    client = client or DeepSeekClient()
    return client.chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(payload)},
        ],
        temperature=temperature,
        max_tokens=3000,
        model=model,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
    )
