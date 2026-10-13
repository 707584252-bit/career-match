# DeepSeek API 接入完整教程

> 本文档面向「第一次调用大模型 API」的读者。每一步都给出可直接复制执行的命令。
> 文中模型名、价格、参数说明以 DeepSeek 官方文档为准核对，但**厂商随时可能调整**，
> 遇到不一致时请以 <https://api-docs.deepseek.com/zh-cn/> 为准。

---

## 0. 先搞清楚这个项目里大模型负责什么

**这一点必须先说，否则容易误解整个系统。**

```
用户作答 ──► 评分引擎（纯 Python，确定性）──► 维度得分
                                              │
                                              ├──► 加权推荐引擎（纯 Python，确定性）──► 职业排序
                                              │
                                              └──► DeepSeek（可选）──► 把结论写成一段人话
```

- **算分、匹配、排序** —— 全部由确定性代码完成。同样的作答永远得到同样的结果。
- **大模型** —— 只做一件事：把结构化结论翻译成一份可读的个性化解读。

所以：**没有 API Key，整个工具照样能用**，只是少一段叙述文字。如果模型胡说八道，也污染不了推荐结果。

这样设计的原因很直接：让一个概率模型参与打分，结果就不可复现、不可审计，出了问题也查不出来。

---

## 1. 获取 API Key

### 1.1 注册与实名

1. 打开 <https://platform.deepseek.com/>
2. 用手机号或邮箱注册账号
3. 完成实名认证（国内调用大模型 API 的合规要求，个人身份证即可）
4. 进入 **充值** 页面充值。**建议先充 10 元**——按本项目的用量，10 元能跑几千次报告。

### 1.2 创建 Key

1. 左侧菜单进入 **API Keys**
2. 点击 **创建 API Key**
3. 起个名字（比如 `career-compass`），创建
4. **Key 只显示一次**（形如 `sk-xxxxxxxxxxxxxxxx`），立刻复制保存

> ⚠️ **不要把 Key 写进代码里提交到 GitHub。**
> 正确做法是环境变量或 `.env` 文件，并且把 `.env` 加进 `.gitignore`（本项目已配好）。
> 已经泄露的 Key 请立刻在控制台删除重建。
>
> 另外提醒：`.env` 只是**本地约定**，不是加密。它不是密钥保险箱，别把生产环境的 Key 放在里面。

---

## 2. 配置到本项目（选一种）

### 方式 A：环境变量（临时，关掉终端就失效）

**macOS / Linux / Git Bash：**

```bash
export DEEPSEEK_API_KEY=sk-你的key
```

**Windows PowerShell：**

```powershell
$env:DEEPSEEK_API_KEY = "sk-你的key"
```

**Windows CMD：**

```cmd
set DEEPSEEK_API_KEY=sk-你的key
```

### 方式 B：`.env` 文件（推荐，持久且不会被误提交）

在项目根目录创建 `.env`：

```bash
DEEPSEEK_API_KEY=sk-你的key
```

`career-compass` 启动时会自动向上查找并读取 `.env`（实现见 `src/career_compass/llm.py` 的 `load_dotenv()`，纯标准库，约 20 行）。**不需要安装 `python-dotenv`。**

`DEEPSEEK_API_KEY` 之外的键也可以写在里面，但本项目只读这一个。

---

## 3. 验证连通（一条命令）

```bash
career-compass llm-test
```

成功时输出：

```
[..] base_url = https://api.deepseek.com
[..] model    = deepseek-flash
[..] 正在发送测试请求…
[ok] 连通成功，模型回复：连通
```

失败时的输出与对应原因：

| 输出 | 原因 | 解决 |
| --- | --- | --- |
| `[x] 未检测到 API Key` | 环境变量没生效，或 `.env` 不在查找路径上 | 确认 `.env` 在项目根目录；PowerShell 设完变量要新开一个终端 |
| `HTTP 401` | Key 错误、已删除或复制时多了空格 | 重新创建 Key，注意首尾不要有空格或引号 |
| `HTTP 402` | 余额不足 | 去控制台充值 |
| `HTTP 429` | 触发限流 | 降低调用频率，或稍后重试 |
| `HTTP 400` | 请求参数不合法 | 通常是 `model` 名写错了 |
| `网络请求失败` / SSL 错误 | 网络不通或代理问题 | 检查代理设置；本客户端走系统代理 |

---

## 4. 用它生成个性化解读

```bash
career-compass demo --persona tech --llm --html report.html
career-compass report --input me.json --llm --html my-report.html
```

生成的报告会多出「**四、个性化解读（由大模型生成）**」一节。

**失败了会怎样？** 会打印 `[!] 大模型调用失败，已跳过个性化解读，其余报告照常生成。原因：...`，然后**继续正常生成完整报告**。规则引擎的结论永远不受影响。

---

## 5. 模型怎么选

当前 DeepSeek 官方提供两个模型（以官方文档为准）：

| 模型名 | 底层版本 | 上下文 | 最大输出 | 并发上限 | 适合什么 |
| --- | --- | --- | --- | --- | --- |
| `deepseek-flash` ← **本项目默认** | DeepSeek-V4.1-Flash | 1M | 384K | 2500 | 通用对话、写作、内容抽取、分类。**本项目用这个就够了** |
| `deepseek-v4-pro` | DeepSeek-V4-Pro | 1M | 384K | 500 | 最强的推理与分析能力，成本约为 Flash 的 3~4.5 倍 |

> **历史说明**：早期文档里的 `deepseek-chat` / `deepseek-reasoner` 已不再出现在官方模型列表中。
> 如果你在别处的旧代码里见到它们，请注意核对官网当前值，不要直接照搬。
> 本项目通过 `--model` 参数或 `DeepSeekClient(model=...)` 支持任意模型名，模型升级时不需要改代码。

**本项目为什么默认用 `deepseek-flash`？**

写一份职业解读报告是**表达型任务**，不是数学证明。Flash 在这个任务上已经足够，而且便宜、快。用 Pro 或开思考模式，成本翻好几倍，输出质量不会有可感知的提升。

想用更强的：

```bash
career-compass demo --llm --model deepseek-v4-pro --html report.html
```

---

## 6. 思考模式（thinking）——什么时候该开

DeepSeek 模型支持「思考模式」：先输出一段思维链，再给最终答案。

**官方默认是开启的**，本项目**默认帮你关掉**。原因：

1. 写报告不需要思维链，开了只会更慢更贵；
2. **思考模式下 `temperature` 会被忽略**（官方明确说明：设置不报错，但不生效）。

### 参数写法

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `thinking` | `{"type": "enabled"}` / `{"type": "disabled"}` | 思考模式开关 |
| `reasoning_effort` | `"low"` / `"high"` / `"max"` | 思考强度，默认 `high` |

### 本项目里的用法

```bash
career-compass demo --llm --reasoning --html report.html
```

或在代码里：

```python
from career_compass.llm import DeepSeekClient

client = DeepSeekClient()

# 普通模式（默认）——temperature 生效
text = client.chat(
    [{"role": "user", "content": "用三句话介绍你自己"}],
    temperature=1.0,
)

# 思考模式——temperature 被忽略，可指定思考强度
result = client.chat_detailed(
    [{"role": "user", "content": "帮我分析这个逻辑谬误在哪"}],
    thinking=True,
    reasoning_effort="max",
)
print(result["reasoning_content"])   # 思维链
print(result["content"])             # 最终答案
```

**什么时候值得开思考模式？** 需要多步推理的任务：逻辑题解析、复杂的方案权衡、代码调试。
本项目里唯一的候选场景是「想让模型对分数之间的**冲突**做更深层的因果分析」——这时可以试试：

```bash
career-compass report --input me.json --llm --reasoning --html deep.html
```

---

## 7. temperature 怎么设

官方给出的场景建议表：

| 场景 | 建议温度 |
| --- | --- |
| 代码生成 / 数学解题 | 0.0 |
| 数据抽取 / 分析 | 1.0 |
| 通用对话 | 1.3 |
| 翻译 | 1.3 |
| 创意类写作 / 诗歌创作 | 1.5 |

本项目生成报告时用 **1.0**。理由：报告的价值在于**忠实解读已算出的数据**，而不是自由发挥。调到 1.3~1.5 文风会更生动，但也更容易开始"编"——对那些分数背后并没有的东西做过度联想。

想改的话，在代码里传 `temperature=` 即可：

```python
from career_compass.llm import generate_narrative

text = generate_narrative(payload, temperature=1.3)   # 更活泼的文风
```

---

## 8. 费用估算

### 8.1 官方价格（人民币，每 100 万 tokens）

| | `deepseek-flash` 空闲时段 | `deepseek-flash` 高峰时段 | `deepseek-v4-pro` 空闲 | `deepseek-v4-pro` 高峰 |
| --- | --- | --- | --- | --- |
| 输入（缓存命中） | ¥0.02 | ¥0.04 | ¥0.15 | ¥0.30 |
| 输入（缓存未命中） | ¥1 | ¥2 | ¥4.5 | ¥9.0 |
| 输出 | ¥4 | ¥8 | ¥13.5 | ¥27.0 |

**高峰时段定义**：北京时间**周一至周五**（不含法定节假日）**9:00–12:00、14:00–18:00**。
其余时段（含周末与法定节假日全天）均为**空闲时段，价格为高峰的一半**。

> 结论：**晚上和周末跑，便宜一半。** 批量生成报告的话安排在这两个时段。

**自动上下文缓存**：DeepSeek 会把请求前缀按 64 token 分块缓存。本项目每次调用的 `system` 提示词完全相同，因此在第一次调用之后，这部分输入会命中缓存，按命中价计费——比未命中价便宜 **50 倍**。你什么都不用做，它默认开启。

### 8.2 本项目的实际成本

一次报告调用的量级：

- 输入：system 提示词约 400 tokens + 结构化数据约 1200 tokens ≈ 1600 tokens（其中 system 部分可命中缓存）
- 输出：约 1500 tokens

按 `deepseek-flash` 空闲时段计算：

```
输入: 1600 / 1,000,000 × ¥1  ≈ ¥0.0016
输出: 1500 / 1,000,000 × ¥4  ≈ ¥0.0060
────────────────────────────────────
单次合计                      ≈ ¥0.008
```

**一次不到 1 分钱。** 充 10 元大约能跑 **1200 次**报告。

（用 `deepseek-v4-pro` 或开思考模式，成本会上升 3~10 倍，依然是「分」的量级。）

---

## 9. 用 OpenAI 官方 SDK 调用（如果你更习惯那种写法）

DeepSeek 兼容 OpenAI 与 Anthropic 的 API 格式，改两个地方即可：

```bash
pip install openai
```

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-你的key",
    base_url="https://api.deepseek.com",     # 唯一需要改的地方之一
)

resp = client.chat.completions.create(
    model="deepseek-flash",                  # 唯一需要改的地方之二
    messages=[
        {"role": "system", "content": "你是一位资深的职业发展咨询顾问。"},
        {"role": "user", "content": "帮我把这段测评结论写成一段解读。"},
    ],
    temperature=1.0,
    # 思考模式参数在 OpenAI SDK 里必须放进 extra_body
    extra_body={"thinking": {"type": "disabled"}},
)
print(resp.choices[0].message.content)
```

> `thinking` 不是 OpenAI 的标准参数，用 SDK 时必须通过 `extra_body` 传，否则会被过滤掉。

**那为什么本项目不用 OpenAI SDK？**
因为不想为了调一个接口就引入一个依赖树。`src/career_compass/llm.py` 用标准库 `urllib` 直接 POST，约 200 行，包含重试、超时、错误分类和 `.env` 读取。这样 `pip install career-compass` 不会装进任何第三方包，clone 下来就能跑。

只有当你确实需要 SDK 的高级特性（流式、批量、异步）时，才值得装。

---

## 10. 流式输出（可选，仅 SDK 场景）

本项目默认关闭流式（报告是一次性生成完再写文件的），但如果你要接到自己的 Web 前端，流式体验更好：

```python
stream = client.chat.completions.create(
    model="deepseek-flash",
    messages=[{"role": "user", "content": "写一段话"}],
    stream=True,
)
for chunk in stream:
    delta = chunk.choices[0].delta.content
    if delta:
        print(delta, end="", flush=True)
```

想在本项目的客户端上加流式，改 `_post()` 里的 `"stream": False` 并处理 SSE 分块即可——不难，但会让代码复杂度上一个台阶，所以默认没做。

---

## 11. 安全与合规提醒

这一节请认真看。

1. **上传的数据会离开你的机器。** 报告请求里包含用户的作答与得分。虽然本项目不上传姓名、身份证等直接标识信息，但**作答记录本身可能被视为个人信息**。如果你要把它做成面向公众的服务，请先做好告知与授权。

2. **不要往提示词里放敏感数据。** 特别注意：不要把你替换后的真实职业数据里含有的内部薪酬、人员信息塞进提示词。

3. **`.env` 不是保险箱。** 它只是本地约定文件。服务器部署请用真正的密钥管理（环境变量注入、KMS、Secrets Manager）。

4. **报告是公开可访问的。** `career-compass` 生成的 HTML 报告如果部署到公网，拿到链接的人都能打开。**不要在里面填真实姓名、真实薪酬、健康状况等隐私信息。** 项目生成的报告默认只含维度得分与职业推荐，不含个人标识——但你自己往里加内容时要注意。

5. **大模型的输出需要人工复核。** 即使系统提示词里写了「不得编造」，模型仍可能过度联想。本项目在提示词中做了三重约束（禁止编造、必须提示数据质量风险、必须带免责声明），并在渲染层对大模型返回的内容做了 HTML 转义防止 XSS，但这些都**不能替代你自己读一遍**。

6. **跨境数据传输。** 如果你的使用场景受特定合规要求约束（如医疗、金融、政务），请先确认调用境外/境内 API 是否符合你的合规要求。

---

## 12. 常见报错速查

| 现象 | 原因与处理 |
| --- | --- |
| `MissingAPIKeyError` | 没配 Key。运行 `career-compass llm-test` 看具体提示 |
| `HTTP 401` | Key 失效。检查是否多了空格/引号，或已在控制台删除 |
| `HTTP 402 Insufficient Balance` | 余额不足，去充值 |
| `HTTP 429` | 限流。客户端已内置指数退避重试 2 次；仍失败就放慢频率 |
| `HTTP 400 model not found` | `--model` 写错了。用 `deepseek-flash` 或 `deepseek-v4-pro` |
| 报错说 `reasoning_effort` 不合法 | 只能是 `low` / `high` / `max`。本项目在发送前会本地校验并抛出明确错误 |
| 设了 `temperature` 却像没生效 | 思考模式会忽略它。加 `thinking` 关闭，或不传 `--reasoning` |
| 返回内容为空字符串 | 多是 `max_tokens` 太小被截断，或思考模式把额度耗在思维链上了 |
| 中文变成乱码 | 客户端全程用 UTF-8 编解码，若出现乱码请检查你的终端编码 |
| 网络超时 | 默认 120 秒。思考模式 + 长输出可能需要调大 `DeepSeekClient(timeout=300)` |

客户端内置的重试策略：**4xx（除 429）不重试**（参数或鉴权错误，重试无意义），
网络错误与 429 按 1.5 秒起步指数退避重试 2 次。

---

## 13. 一句话总结

```bash
# 三行搞定
echo "DEEPSEEK_API_KEY=sk-你的key" > .env
career-compass llm-test
career-compass demo --llm --html report.html
```

成本不到 1 分钱一次，跑不通也不影响主流程。剩下的都可以慢慢调。
