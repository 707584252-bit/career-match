# career-compass · 职业罗盘

> 一套可复现、可解释、可替换数据的**职业能力测评与加权职业推荐引擎**。
> 21 个维度、65 道题、25 个职业画像、12 位名人典范、行业大盘修正，**零第三方依赖**，纯 Python 标准库实现。

[![CI](https://github.com/707584252-bit/career-match/actions/workflows/ci.yml/badge.svg)](https://github.com/707584252-bit/career-match/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](pyproject.toml)

---

## 目录

- [它解决什么问题](#它解决什么问题)
- [30 秒上手](#30-秒上手)
- [测评体系设计](#测评体系设计)
- [评分与推荐算法](#评分与推荐算法)
- [接入 DeepSeek API](#接入-deepseek-api)
- [项目结构](#项目结构)
- [如何替换为真实数据](#如何替换为真实数据)
- [作为库调用](#作为库调用)
- [开发与测试](#开发与测试)
- [局限与免责声明](#局限与免责声明)
- [路线图](#路线图)
- [License](#license)

---

## 它解决什么问题

网上的「职业测试」大多有三类毛病：

1. **黑盒**——给你一个结果，但不告诉你为什么，也无法复核。
2. **数据编造**——题库和职业数据是随手写的，没有理论依据，也没有出处。
3. **一次性**——跑完就完了，数据不能导出、不能改、不能接自己的系统。

career-compass 的设计取向正好相反：

| 特性 | 本项目的做法 |
| --- | --- |
| 可解释 | 每个结论都能回溯到具体维度得分与分差，附「优势 / 差距 / 提升建议」 |
| 可审计 | 算法是不到 200 行的纯函数，有 168 项单元测试；数据文件带 `_meta.note` 标注出处与替换方法 |
| 可替换 | 题库、职业画像、名人画像、行业大盘是 4 个独立 JSON，改数据不用改代码 |
| 可扩展 | 有 CLI、有 Python API、有浏览器答题页（`questionnaire` 子命令），可以接你自己的前端 |
| 零依赖 | 只用标准库（含 `urllib` 直连 DeepSeek），`pip install` 不会拉进一坨包 |

**它不会做什么**：不做心理诊断，不做就业承诺，不做薪酬预测。它是一套**结构化的自我探索工具**，不是算命。

---

## 30 秒上手

```bash
git clone https://github.com/707584252-bit/career-match.git
cd career-match
pip install -e .
```

不需要任何 API Key，先看一份完整报告：

```bash
career-compass demo --html report.html --open
```

`--open` 会用系统默认浏览器直接打开它；不加就只看下面的文字摘要。

用浏览器打开 `report.html`，你会看到：

- 四大维度雷达图 + 霍兰德六角雷达图（**内联 SVG 手绘，无外部依赖，可离线打开**）
- 21 个子维度的横向条形明细
- 加权排序后的职业推荐，每条附匹配度、行业大盘分、优势、差距、提升建议、可参考的名人典范

换一个人格模板再看一次（5 套内置模板：`tech` / `people` / `business` / `creative` / `steady`）：

```bash
career-compass demo --persona creative --html creative.html
career-compass demo --persona people   --html people.html
```

自己真正做一遍 —— **推荐用浏览器答题页**（65 题约 10 分钟，可随时中断续答）：

```bash
career-compass questionnaire --open          # 生成 questionnaire.html 并打开
```

在页面上点选作答，答完点底部「**导出作答文件**」，然后一条命令导入 + 出报告 + 打开：

```bash
python scripts/import_answers.py --open           # 报告会自动在浏览器里弹出
python scripts/import_answers.py --open --llm     # 再加 DeepSeek 个性化解读
```

`import_answers.py` 会自动去找你的作答 —— 先读剪贴板，再去「下载」文件夹里找最新的
`career-compass-answers*.json`。所以「导出文件」和「复制作答」两个按钮都管用，
不需要自己填路径。也可以显式指定：

```bash
python scripts/import_answers.py --from ~/Downloads/career-compass-answers.json --open
```

> 答题页是**单文件、零外部依赖、不联网**的 HTML：双击就能打开，作答只存在你自己
> 浏览器的 `localStorage` 里，不上传任何地方。页面里**不含答案字段**（有测试守着）。

也可以留在终端里答（不适合 65 题，但适合脚本化场景）：

```bash
career-compass run --save-answers me.json --html my-report.html --md my-report.md
```

之后随时用同一份作答重新出报告：

```bash
career-compass report --input me.json --html my-report.html --open
```

只想拿结构化数据接自己的系统：

```bash
career-compass score --input me.json -o result.json
career-compass questions -o questionnaire.json   # 导出问卷（不含答案），可接自建前端
```

全部子命令：

| 命令 | 作用 |
| --- | --- |
| `demo` | 用内置人格模板直接出报告，无需答题 |
| **`questionnaire`** | **生成浏览器答题页（单文件 HTML，推荐）** |
| `run` | 终端交互式答题并生成报告 |
| `report` | 从已保存的作答文件重新生成报告 |
| `score` | 只输出结构化评分 JSON |
| `questions` | 导出问卷 JSON（刻意剔除答案字段，避免泄漏） |
| `list-careers` | 列出职业库与行业大盘数据 |
| `llm-test` | 验证 DeepSeek API 配置是否正确 |

---

## 测评体系设计

### 四大维度 / 21 个子维度

| 维度 | 子维度 | 计分方式 | 题量 |
| --- | --- | --- | --- |
| **学术能力** | 逻辑推理、数理运算、语言理解、空间想象 | **客观题**（有唯一正确答案） | 14 |
| **技能特长** | 技术实操、创意设计、沟通协作、组织管理 | 李克特自评（1–5） | 12 |
| **个人特质** | 开放性、尽责性、外向性、宜人性、情绪稳定性、坚毅性、风险偏好 | 李克特自评（1–5） | 21 |
| **兴趣** | 现实型 R、研究型 I、艺术型 A、社会型 S、企业型 E、常规型 C | 李克特自评（1–5） | 18 |

合计 **65 题**（含 3 道反向计分题，用于识别「一路同意」的无效作答）。

### 关键设计决策：为什么学术能力用客观题，其余用自评题？

这是整套体系里最重要的一个判断：

- **能力必须被测量，不能被自报。** 「我逻辑能力强」和「我能做对逻辑题」是两回事。自评能力会被达克效应系统性扭曲——能力越弱的人越容易高估自己。所以学术能力维度用**有标准答案的客观题**，如实反映表现。
- **兴趣和特质只能被自报。** 没有人能通过一道题测出你「喜不喜欢和人打交道」，这属于主观偏好，必须直接问。这也符合霍兰德本人对该类工具的使用立场。
- 题目设计参照了公开的成熟量表与标准化考试题型（GRE/GMAT 分析性推理、公务员行测、Holland RIASEC、Big Five、Duckworth Grit Scale），但**均为自编中文题项**，每道题的 `source` 字段标注了具体参照来源。理论上这是「基于公开构念的工具开发」，不是原量表的翻译或复制。

> 完整的设计依据、信度效度讨论、以及本项目**明确未做**的检验，见 [`docs/THEORY.md`](docs/THEORY.md)。如果你要拿它做严肃研究，请先读那一份。

---

## 评分与推荐算法

### 第一步：单题计分

**客观题**（难度加权，让答对难题比答对简单题值钱）：

```
得分 = Σ(题权重 × 难度权重 × 是否答对 × 100) / Σ(题权重 × 难度权重)
难度权重 = 0.4 + 0.6 × difficulty          # 把 [0,1] 映射到 [0.4, 1.0]
```

**李克特题**（反向题先翻转，再线性映射到 0–100）：

```
得分 = (均值 - 1) / (5 - 1) × 100
一致性信度 = 1 - 标准差 / 50               # 用于识别乱答、前后矛盾
```

### 第二步：数据质量把关

不只算分，还要判断这份作答**能不能信**：

```
质量指数 = 0.55 × 平均作答一致性 + 0.45 × 完成率
```

触发以下任一情况会在报告顶部显式提示，而不是静默出结论：

- 有任何维度未作答 → 按中性值 50 填充并声明
- 完成率 < 90%
- 作答一致性 < 60%（同一维度内前后矛盾）
- 某一选项占比 ≥ 85%（直线作答）

### 第三步：霍兰德代码

对 6 个兴趣维度排序，取前三得到一个三字代码（如 `IRC`），用于可解释性展示与同分排序。

### 第四步：加权匹配度

职业画像是一张稀疏向量——**只列出该职业真正产生区分度的维度**，未列出的不参与计算（组权重会在实际参与的组之间重新归一化），避免把「未指定」误当成「要求中等」。

单维度拟合度使用**非线性惩罚**而非线性差值：

```
sim = clamp(1 - (|用户得分 - 职业要求| / 55) ^ 1.3, 0, 1)

分差   0     5     10    20    30    45    55
拟合  1.00  0.96  0.89  0.73  0.55  0.23  0.00
```

> **为什么要非线性？** 早期版本用的是 `1 - |diff|/100`。实测发现它过于宽容——差 20 分只扣 0.20，导致 25 个职业里有一半都落在 78~88 区间，「临床医生」几乎出现在所有人（包括艺术型）的 Top5 里。改成幂次惩罚后，区分度才真正出来。这是一个被测试逼出来的修正，不是拍脑袋。

**为什么两个方向都罚？** 能力远超岗位要求（overqualification）在组织行为学中同样与较低的岗位满意度和更高的离职率相关；对兴趣与特质维度而言，取向错配本身就是双向代价。所以采用对称惩罚。

组权重（可在代码中修改）：

```python
DEFAULT_GROUP_WEIGHTS = {
    "interest": 0.35,   # 兴趣——对满意度与留任率的预测力通常最高
    "trait":    0.25,   # 特质
    "skill":    0.25,   # 技能
    "academic": 0.15,   # 学术能力——是门槛，但不是长期满意度主因
}
```

### 第五步：行业大盘修正

```
market = 景气度 × 0.45 + 增长性 × 0.25 + (1 - AI替代风险) × 0.30
final  = 0.80 × match + 0.20 × market
```

**为什么匹配度占 80%？** 大盘数据用于在能力相近的备选之间做排序微调，而不能把一个「非常不适合」的职业因为「行业很热」推上去。把 `market_blend` 调高会立刻改变排序——这一点有专门的测试守着（`test_market_blend_shifts_ranking_between_two_careers`）。

### 第六步：差距分析与建议

对每个推荐职业，逐维度对比用户得分与该职业要求，分差 ≥ 12 分即判定为「优势」或「差距」，并对差距维度给出**具体到动作**的提升建议（不是「多练习」这种空话）。

> 注意：`trait.risk`（风险偏好）、`trait.extraversion`（外向性）、`trait.agreeableness`（宜人性）被标记为**中性维度**——它们没有「越高越好」的方向，报告中会明确说明这一点，不会把「内向」写成缺陷。

---

## 接入 DeepSeek API

规则引擎给出的是一份结构化结论，大模型可以把它变成一份读起来像人写的个性化解读。

**先看清楚这个分工**：模型只负责**叙述与解读**，不参与算分、不参与推荐排序。分数永远是确定性代码算出来的。这样即使模型胡说，推荐结果也不会被污染。

### 最简三步

```bash
# 1. 去 https://platform.deepseek.com/api_keys 创建 Key（形如 sk-xxxxxxxx）

# 2. 二选一配置
#    方式 A：环境变量
export DEEPSEEK_API_KEY=sk-xxxxxxxx          # Windows PowerShell: $env:DEEPSEEK_API_KEY="sk-xxxxxxxx"
#    方式 B：在项目根目录建 .env 文件（推荐，会被自动读取）
echo "DEEPSEEK_API_KEY=sk-xxxxxxxx" > .env

# 3. 验证
career-compass llm-test
# [ok] 连通成功，模型回复：连通
```

然后加 `--llm` 即可：

```bash
career-compass demo --persona tech --llm --html report.html
career-compass report --input me.json --llm --html my-report.html
career-compass demo --llm --model deepseek-reasoner --html report.html   # 深度推理模型
```

**没有 API Key 会怎样？** 不会崩。`--llm` 失败时会打印原因并**照常生成其余报告部分**，规则引擎的结论一直都在。

> 完整的 DeepSeek 接入教程（注册、计费、模型选型、OpenAI SDK 兼容写法、流式输出、常见报错排查、成本估算、生产环境注意事项）见 **[`docs/DEEPSEEK.md`](docs/DEEPSEEK.md)**。

---

## 项目结构

```
career-compass/
├── data/                        # 可替换的数据层（改数据不用改代码）
│   ├── questions.json           #   65 道题 + 维度体系 + 量表定义
│   ├── careers.json             #   25 个职业的 21 维画像 + 霍兰德代码
│   ├── role_models.json         #   12 位名人典范的能力画像
│   └── market_stats.json        #   行业景气 / 增长 / AI 替代风险
├── src/career_compass/
│   ├── models.py                # 纯数据结构（无业务逻辑，便于测试）
│   ├── data_loader.py           # 数据定位与解析（带缓存）
│   ├── scoring.py               # 评分引擎（纯函数，不碰 IO）
│   ├── recommend.py             # 加权推荐引擎（纯函数）
│   ├── report.py                # Markdown / 内联 SVG 的 HTML 报告
│   ├── questionnaire.py         # 浏览器答题页生成（单文件自包含 HTML）
│   ├── llm.py                   # DeepSeek 客户端（纯标准库 urllib）
│   ├── console.py               # 跨平台 UTF-8 输出（修英文 Windows 中文崩溃）
│   └── cli.py                   # 命令行入口
├── scripts/
│   └── import_answers.py        # 导入浏览器作答 → 直接出报告
├── tests/                       # 168 项测试
│   ├── test_scoring.py          #   计分、反向题、一致性、空数据
│   ├── test_recommend.py        #   相似度曲线、权重、排序、大盘修正
│   ├── test_data_integrity.py   #   数据一改就报警（id 引用、取值域、覆盖率）
│   ├── test_questionnaire.py    #   防泄题、作答编码契约、导入脚本
│   ├── test_llm_errors.py       #   错误码映射、重试策略、余额查询
│   └── test_cli.py              #   端到端、零外链、XSS 转义、LLM 降级
├── examples/sample_answers.json
└── docs/
    ├── DEEPSEEK.md              # DeepSeek 接入完整教程
    └── THEORY.md                # 理论依据与信度效度说明
```

架构分层：**数据层 → 计算层 → 渲染层**，只允许上层调下层，渲染函数之间不互相调用，避免循环依赖。

---

## 如何替换为真实数据

这是本项目的核心可扩展点。四个 JSON 都可以独立替换：

### 1. 替换题库 `data/questions.json`

```jsonc
{
  "id": "LOG05",
  "dim": "academic.logic",        // 必须是 _meta.dimensions 里的 key
  "type": "objective",            // objective | likert
  "stem": "题干内容",
  "options": ["A", "B", "C", "D"],
  "answer": 2,                    // 仅客观题需要，选项下标
  "difficulty": 0.6,              // 0~1，用于难度加权
  "weight": 1.0,
  "reverse": false,               // 仅自评题，true 表示反向计分
  "source": "题项参照来源说明"
}
```

改完后跑 `pytest`——`test_data_integrity.py` 会检查维度是否已定义、每题是否 ≥ 3 题、正确答案位置是否过于集中（防止「全选 A」刷分）。

### 2. 替换职业画像 `data/careers.json`

`profile` 是稀疏向量，只填你**有依据**的维度：

```jsonc
"profile": {
  "academic.logic": 82,           // 0~100 的要求强度
  "skill.tech": 88,
  "interest.investigative": 85
}
```

建议的数据来源（优先级从高到低）：

1. **O*NET OnLine**——美国劳工部职业信息系统，公开提供每个职业的 Ability / Interest / Work Activity / Skill 评分，是国际通用的职业分析金标准，可免费查询与下载。
2. **Holland RIASEC 职业代码手册**——已在大量职业分类研究中给出各职业的三字代码，可直接用于校准 `holland` 字段。
3. **《中华人民共和国职业分类大典》**——职业名称与分类的中文标准口径。
4. **招聘平台岗位描述（JD）**——用 NLP 抽取技能要求频次，作为画像的实证校准。
5. **行业研报**——用于 `market_stats.json` 的景气度与增长性。

> 项目自带的数值是**专家赋值的理性估计**，用于跑通算法链路。它不精确，请以自己的行业一手数据覆盖。

### 3. 替换行业大盘 `data/market_stats.json`

```jsonc
"software_engineer": {
  "outlook": 0.86,      // 景气度 0~1
  "growth": 0.72,       // 增长性 0~1
  "ai_risk": 0.50,      // 自动化暴露度 0~1（越高越危险）
  "salary_band": "¥15–45万/年",
  "note": "补充说明"
}
```

替换后请同步更新 `_meta.sources`，保持数据可溯源。

### 4. 替换名人典范 `data/role_models.json`

`traits` 同样是稀疏向量。它的作用有两个：为推荐结果提供具象参照；作为职业画像的先验校准锚点——**如果某职业画像和该领域公认高手的能力分布严重偏离，说明画像需要复核**。

> 名人画像是对公开资料中**可观察到的能力倾向**的概括，不是心理测量结果，也不构成对其真实人格的论断。
>
> **每新增一个名人，必须至少被一个职业引用**，否则 `test_every_role_model_is_referenced` 会失败（这个测试就是为了防止数据孤儿）。

---

## 作为库调用

```python
from career_compass import (
    load_questions, load_dimension_names,
    compute_profile, recommend, render_html, deepseek_narrative,
)

questions = load_questions()

# 你的前端传回来的作答：客观题为选项下标，自评题为 1~5
answers = {"LOG01": 2, "NUM01": 1, "SKT01": 4, "INI03": 5, ...}

profile = compute_profile(questions, answers, load_dimension_names())
print(profile.group_scores)   # {'academic': 79.2, 'skill': 66.7, ...}
print(profile.holland_code)   # 'IRC'
print(profile.quality)        # 0.85
print(profile.warnings)       # ['完成率仅 82%...']

recs = recommend(profile, top_n=5)
for r in recs:
    print(r.career.name, r.final_score, r.match_score, r.market_score)
    print('  优势:', r.strengths)
    print('  差距:', r.gaps)

html = render_html(profile, recs)
open("report.html", "w", encoding="utf-8").write(html)
```

想调参：

```python
from career_compass.recommend import recommend

# 提高行业大盘的权重
recs = recommend(profile, top_n=5, match_blend=0.6, market_blend=0.4)

# 换个组权重：只看兴趣和特质
from career_compass.recommend import match_profile
score, per_group = match_profile(
    profile,
    career_profile,
    group_weights={"interest": 0.6, "trait": 0.4, "skill": 0.0, "academic": 0.0},
)
```

LLM 单独用：

```python
from career_compass.llm import DeepSeekClient          # pip 之外零依赖
client = DeepSeekClient()                               # 自动读 DEEPSEEK_API_KEY / .env
print(client.chat([{"role": "user", "content": "你好"}]))
```

---

## 开发与测试

```bash
pip install -e ".[dev]"     # 装 pytest / ruff
pytest                      # 168 项测试
pytest -q tests/test_recommend.py
ruff check src tests
```

测试覆盖的重点（这些都是**踩过的坑**，不是凑数）：

- 空作答不崩、按中性值填充并产生提示
- 反向计分题的正确性（正反两向得分互补）
- 一致性信度能识别两极摇摆的作答
- 直线作答检测
- 相似度曲线的参考点与对称性
- 职业画像未列出的维度不参与计算、组权重正确重归一化
- 大盘分真的影响排序
- HTML 报告**零外部资源引用**（防止离线打开时样式全丢）
- 大模型返回内容中的 HTML 被转义（XSS 防护）
- 数据 id 引用完整性（名人未被引用、职业缺大盘数据等）

CI 在 Python 3.9 / 3.11 / 3.13 上跑全量测试 + ruff 检查。

---

## 局限与免责声明

请务必读完这一节，尤其是如果你打算严肃使用它。

**方法论上的局限：**

1. **未做正式信度效度检验。** 本项目没有收集真实样本做内部一致性系数（Cronbach's α）、重测信度、结构效度或效标关联效度的检验。它是一套**结构合理的工具**，不是经过心理测量学验证的**量表**。
2. **常模缺失。** 分数是 0–100 的绝对标度，不是相对同龄人/同职业群体的百分位。「65 分」的含义是「该维度自评倾向中等」，不是「超过了 65% 的人」。
3. **自评偏差仍然存在。** 兴趣与特质维度依赖自评，会受社会赞许性、当下心境、题目理解偏差的影响。一致性检查只能发现最粗暴的无效作答。
4. **职业画像是专家赋值。** 25 个职业的 21 维数值是理性估计，不是从岗位数据中拟合出来的。不同赋值会给出不同排序。
5. **行业大盘数据是示例性的。** `market_stats.json` 中的景气度、增长性、AI 替代风险均为演示用途的估计值，不代表任何官方统计口径。
6. **算法本身没有学习能力。** 项目名称里的「根据大数据学习」指的是**用行业统计量与专家画像做加权修正**，不是训练了一个机器学习模型。所有参数都是显式、可读、可改的。

**使用建议：**

把结果当作**结构化的自我探索起点**，而不是结论。它最大的价值不在于告诉你「你该做什么」，而在于逼你面对一些平时不会问自己的问题：你的兴趣和能力是否一致？你愿意为哪些维度付出代价？你放在「差距」里的那些维度，是真的短板，还是你其实根本不想补？

**免责声明：** 本项目输出的一切内容仅供参考，**不构成职业决策、心理诊断、薪酬预测或投资建议**。请勿仅凭本工具做出重大人生决策。使用本工具即表示你理解并接受以上全部局限。

---

## 路线图

- [ ] 补充常模数据：收集匿名作答样本，产出职业群体百分位对照
- [ ] 支持题目乱序与选项乱序（进一步防止作答模式固化）
- [ ] 输出 PDF 报告
- [ ] 提供一个不依赖后端的纯前端版本（复用 `questions` 子命令的导出格式）
- [ ] 增加职业画像的可视化编辑工具（低代码改 `careers.json`）
- [ ] 引入更严谨的能力题模型（如简化的 IRT 二参数模型替代难度加权）
- [ ] 补充英文题项与英文报告，便于国际用户

欢迎提 Issue 讨论。理论或数据上的质疑，比功能请求更有价值。

---

## 贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。简单说：改数据附出处，改算法附测试。

特别欢迎以下贡献：

- 补充有**明确出处**的职业画像数据（O*NET / 职业分类大典 / 行业研报）
- 指出题项设计上的理论问题
- 补充非中国大陆地区的职业与薪酬数据

## License

[MIT](LICENSE) © career-compass contributors

题库与职业画像部分的数据整理自公开资料，使用前请自行核对相应来源的授权条款。
