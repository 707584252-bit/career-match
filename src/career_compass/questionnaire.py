"""浏览器答题页生成器。

命令行逐题作答（``run_interactive``）适合脚本化场景，但对 65 道题来说体验很糟：
终端里看不到全局进度、改前一题要按 ``b`` 一路退回去、关掉窗口就全丢了。

本模块把题库渲染成一个**自包含的单文件 HTML 页面**，用户在浏览器里点选作答：

* 按「组 → 子维度」分区展示，带锚点导航与整体进度条
* 作答实时存进 ``localStorage``，关掉浏览器再打开可以接着答
* 一键导出与 ``save_answers()`` 完全同格式的 JSON，或直接复制到剪贴板

与报告一样，页面**零外部依赖**——不引用任何 CDN、字体或图片，
双击就能在任何断网的机器上打开。

作答编码（与 ``scoring`` 保持一致，不要改）
------------------------------------------
* 客观题：选项的 **0 基下标**（``scoring`` 用 ``answers[q.id] == q.answer`` 判对错）
* 李克特题：原始 **1~5**（反向计分由 ``scoring`` 负责，页面不做任何转换）

安全
----
题目载荷**不包含** ``answer`` 字段——否则打开页面查看源码就能看到答案。
`test_questionnaire.py` 对此有断言。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

from .models import DIMENSION_TREE, GROUP_ORDER, Question

#: 默认导出文件名，也是页面上提示用户去找的名字
DEFAULT_EXPORT_NAME = "career-compass-answers.json"

#: localStorage 的键。带版本号，将来改题目结构时可以平滑失效
STORAGE_KEY = "career-compass-answers-v1"

#: 占位符。用独特的注释标记而非 ``{}``，这样模板里的 CSS/JS 花括号无需转义
_PH_TITLE = "/*__WB_TITLE__*/"
_PH_DATA = "/*__WB_DATA__*/"
_PH_STORAGE = "/*__WB_STORAGE_KEY__*/"
_PH_EXPORT_NAME = "/*__WB_EXPORT_NAME__*/"
_PH_BUILT_AT = "/*__WB_BUILT_AT__*/"
_PH_VERSION = "/*__WB_VERSION__*/"


def build_questionnaire_payload(
    questions: Sequence[Question],
    dim_names: dict[str, str],
    group_names: dict[str, str],
    scale: dict,
) -> dict:
    """把题库整理成页面需要的嵌套结构。

    刻意**丢弃** ``answer`` / ``difficulty`` / ``weight`` / ``source``：
    前两个会泄题，后两个属于出题设计细节，被测者不需要看到。

    Returns:
        ``{"title": str, "labels": [...], "total": int, "groups": [...]}``
    """
    groups: list[dict] = []
    for g in GROUP_ORDER:
        # 按 DIMENSION_TREE 的顺序组织，而不是按题库里的物理顺序，
        # 这样同一子维度的题始终聚在一起，作答体验更连贯。
        dims: list[dict] = []
        for sub in DIMENSION_TREE.get(g, []):
            key = f"{g}.{sub}"
            items = [q for q in questions if q.dim == key]
            if not items:
                continue
            dims.append(
                {
                    "key": key,
                    "name": dim_names.get(key, key),
                    "questions": [
                        {
                            "id": q.id,
                            "type": q.type,
                            "stem": q.stem,
                            "dim": q.dim,
                            # 客观题才有选项；李克特题复用全局量表标签
                            "options": list(q.options) if q.type == "objective" else [],
                        }
                        for q in items
                    ],
                }
            )
        if dims:
            groups.append({"key": g, "name": group_names.get(g, g), "dims": dims})

    total = sum(len(d["questions"]) for grp in groups for d in grp["dims"])
    return {
        "title": "职业能力测评问卷",
        "labels": list(scale.get("labels", [])),
        "groups": groups,
        "total": total,
    }


def render_questionnaire(
    questions: Sequence[Question],
    dim_names: dict[str, str],
    group_names: dict[str, str],
    scale: dict,
    built_at: datetime | None = None,
) -> str:
    """生成完整的答题页 HTML。"""
    payload = build_questionnaire_payload(questions, dim_names, group_names, scale)
    ts = (built_at or datetime.now()).strftime("%Y-%m-%d %H:%M")

    # `<` 转义掉，避免题面里出现 "</script>" 之类内容时把脚本标签提前闭合
    data_js = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")

    return (
        _TEMPLATE.replace(_PH_TITLE, _esc(payload["title"]))
        .replace(_PH_DATA, data_js)
        .replace(_PH_STORAGE, json.dumps(STORAGE_KEY))
        .replace(_PH_EXPORT_NAME, json.dumps(DEFAULT_EXPORT_NAME))
        .replace(_PH_BUILT_AT, ts)
        .replace(_PH_VERSION, json.dumps(_package_version()))
    )


def _package_version() -> str:
    """读取包版本；单独运行时（未安装）退回 ``"unknown"`` 而不是抛异常。"""
    try:
        from . import __version__

        return __version__
    except Exception:  # pragma: no cover - 仅在包结构被破坏时触发
        return "unknown"


def _esc(s: str) -> str:
    """只用于标题等极少数插进 HTML 的位置；题面全部走 JS 的 textContent。"""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------------------
# 模板
# ---------------------------------------------------------------------------

_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>/*__WB_TITLE__*/</title>
<style>
  :root {
    --ink: #1f2430; --ink-soft: #5a6472; --line: #e3e7ee;
    --bg: #ffffff; --bg-soft: #f6f8fb;
    --academic: #3b6fd4; --skill: #0f9d8c; --trait: #c4711f; --interest: #8b5cf6;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0 16px 120px;
    background: var(--bg-soft); color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue",
                 "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    line-height: 1.68; font-size: 16px;
  }
  .wrap { max-width: 860px; margin: 0 auto; }
  header.top { padding: 34px 0 6px; }
  header.top h1 { margin: 0 0 6px; font-size: 27px; letter-spacing: -0.2px; }
  .stamp { color: var(--ink-soft); font-size: 13.5px; }
  .howto {
    background: #fff; border: 1px solid var(--line); border-radius: 16px;
    padding: 16px 20px; margin: 18px 0; font-size: 14.5px; color: var(--ink-soft);
  }
  .howto b { color: var(--ink); }
  .howto ol { margin: 8px 0 0; padding-left: 22px; }
  .howto li { margin: 4px 0; }
  nav.tabs { display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0 6px; }
  nav.tabs a {
    text-decoration: none; color: var(--ink-soft); font-size: 14px;
    background: #fff; border: 1px solid var(--line); border-radius: 999px;
    padding: 6px 14px;
  }
  nav.tabs a:hover { border-color: #c3ccda; color: var(--ink); }
  .panel {
    background: #fff; border: 1px solid var(--line); border-radius: 16px;
    padding: 4px 22px 18px; margin: 16px 0;
  }
  .ghead { display: flex; align-items: center; gap: 10px; padding: 16px 0 4px; }
  .ghead .dot { width: 10px; height: 10px; border-radius: 50%; flex: 0 0 auto; }
  .ghead h2 { margin: 0; font-size: 19px; }
  .dim { margin: 18px 0 6px; }
  .dim-t {
    font-size: 13.5px; font-weight: 700; color: var(--ink-soft);
    border-bottom: 1px solid var(--line); padding-bottom: 6px; margin-bottom: 12px;
  }
  .q { padding: 12px 0; border-bottom: 1px dashed var(--line); }
  .q:last-child { border-bottom: 0; }
  .q.blank { background: #fffdf5; }
  .stem { font-size: 15.5px; margin-bottom: 10px; }
  .stem .idx {
    display: inline-block; min-width: 30px; color: var(--ink-soft);
    font-size: 12.5px; font-variant-numeric: tabular-nums;
  }
  .opts { display: flex; flex-wrap: wrap; gap: 8px; }
  .opts.vert { display: block; }
  label.opt {
    display: flex; align-items: flex-start; gap: 8px; cursor: pointer;
    border: 1px solid var(--line); background: var(--bg-soft);
    border-radius: 10px; padding: 7px 12px; font-size: 14.5px;
    transition: border-color .12s, background .12s;
  }
  label.opt:hover { border-color: #c3ccda; }
  .opts.vert label.opt { margin: 6px 0; }
  label.opt input { margin: 3px 0 0; flex: 0 0 auto; }
  label.opt.sel { border-color: var(--accent, #3b6fd4); background: #eef4ff; }
  label.opt.sel .lt { font-weight: 600; }
  .lt { color: var(--ink-soft); }
  label.opt.sel .lt { color: var(--ink); }

  /* 底部固定操作条 */
  .bar {
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 20;
    background: rgba(255,255,255,.96); border-top: 1px solid var(--line);
    backdrop-filter: blur(6px);
  }
  .bar-in {
    max-width: 860px; margin: 0 auto; padding: 12px 16px;
    display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  }
  .prog { flex: 1 1 200px; min-width: 160px; }
  .prog .txt { font-size: 13px; color: var(--ink-soft); margin-bottom: 5px; }
  .prog .txt b { color: var(--ink); font-variant-numeric: tabular-nums; }
  .track { height: 8px; background: var(--line); border-radius: 5px; overflow: hidden; }
  .track i { display: block; height: 100%; width: 0; background: #3b6fd4; border-radius: 5px;
             transition: width .18s ease; }
  button {
    font: inherit; font-size: 14px; cursor: pointer;
    border-radius: 10px; padding: 9px 16px; border: 1px solid var(--line);
    background: #fff; color: var(--ink);
  }
  button:hover { border-color: #c3ccda; }
  button.primary { background: #3b6fd4; border-color: #3b6fd4; color: #fff; }
  button.primary:hover { background: #325fb8; }
  button.ghost { color: var(--ink-soft); }
  .toast {
    position: fixed; left: 50%; bottom: 96px; transform: translateX(-50%) translateY(10px);
    background: #1f2430; color: #fff; font-size: 14px; padding: 9px 18px;
    border-radius: 10px; opacity: 0; pointer-events: none; transition: all .2s ease; z-index: 30;
  }
  .toast.on { opacity: 1; transform: translateX(-50%) translateY(0); }
  footer { color: var(--ink-soft); font-size: 13px; padding: 26px 0 10px; }
  footer a { color: var(--ink-soft); }
  @media (max-width: 560px) {
    .opts { display: block; }
    .opts label.opt { margin: 6px 0; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>职业能力测评问卷</h1>
    <div class="stamp" id="meta">正在载入题目…</div>
  </header>

  <div class="howto">
    <b>怎么用</b>
    <ol>
      <li>按顺序点选即可，答案会自动存在这台电脑的浏览器里，<b>中途关掉页面也不会丢</b>。</li>
      <li>答完后点底部 <b>「导出作答文件」</b>，会下载一个 JSON 文件。</li>
      <li>把那个文件交给命令行生成报告（页面底部有确切命令）。</li>
    </ol>
    <div style="margin-top:8px">
      没有标准答案，也没有时间限制。凭第一反应作答即可；漏答的题目最终会被按「中性」处理，
      所以尽量答完，但不必纠结。
    </div>
  </div>

  <nav class="tabs" id="tabs"></nav>
  <div id="form"></div>

  <footer>
    本页面由 career-compass 生成 · 生成时间 /*__WB_BUILT_AT__*/ · 单文件、零外部依赖、不联网。
  </footer>
</div>

<div class="bar">
  <div class="bar-in">
    <div class="prog">
      <div class="txt">已答 <b id="done">0</b> / <b id="total">0</b> 题 <span id="pct"></span></div>
      <div class="track"><i id="barfill"></i></div>
    </div>
    <button id="btn-jump" class="ghost">跳到未答</button>
    <button id="btn-copy">复制作答</button>
    <button id="btn-export" class="primary">导出作答文件</button>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
(function () {
  "use strict";

  var DATA = /*__WB_DATA__*/;
  var STORAGE_KEY = /*__WB_STORAGE_KEY__*/;
  var EXPORT_NAME = /*__WB_EXPORT_NAME__*/;
  var COLORS = {
    academic: "var(--academic)", skill: "var(--skill)",
    trait: "var(--trait)", interest: "var(--interest)"
  };

  var answers = {};
  var flat = [];   // 按展示顺序拍平的题目 id + 类型，用于进度与"跳到未答"

  // ---- 读取本地存档 -----------------------------------------------------
  function loadSaved() {
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return {};
      var obj = JSON.parse(raw);
      return (obj && typeof obj === "object") ? obj : {};
    } catch (e) {
      return {};   // 隐私模式或存档损坏都不该让页面挂掉
    }
  }
  function save() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(answers));
    } catch (e) { /* 存不了就算了，页面仍可正常作答与导出 */ }
  }

  // ---- 渲染 -------------------------------------------------------------
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function buildForm() {
    var form = document.getElementById("form");
    var tabs = document.getElementById("tabs");

    DATA.groups.forEach(function (g) {
      var anchor = "g-" + g.key;

      var tab = el("a", null, g.name);
      tab.href = "#" + anchor;
      tabs.appendChild(tab);

      var panel = el("section", "panel");
      panel.id = anchor;
      panel.style.setProperty("--accent", COLORS[g.key] || "#3b6fd4");

      var gh = el("div", "ghead");
      var dot = el("span", "dot");
      dot.style.background = COLORS[g.key] || "#3b6fd4";
      gh.appendChild(dot);
      gh.appendChild(el("h2", null, g.name));
      panel.appendChild(gh);

      g.dims.forEach(function (d) {
        panel.appendChild(el("div", "dim-t", d.name));
        var box = el("div", "dim");
        d.questions.forEach(function (q) {
          flat.push(q.id);
          box.appendChild(renderQuestion(q, g.key));
        });
        panel.appendChild(box);
      });

      form.appendChild(panel);
    });

    document.getElementById("total").textContent = String(flat.length);
    document.getElementById("meta").textContent =
      DATA.groups.length + " 个维度组 · " + flat.length + " 道题 · 作答自动保存";
  }

  function renderQuestion(q, groupKey) {
    var wrap = el("div", "q");
    wrap.dataset.qid = q.id;

    var stem = el("div", "stem");
    stem.appendChild(el("span", "idx", ""));
    stem.appendChild(document.createTextNode(q.stem));
    wrap.appendChild(stem);

    // 客观题用竖排（选项文字较长），李克特用横排
    var isObj = q.type === "objective";
    var opts = el("div", "opts" + (isObj ? " vert" : ""));
    var labels = isObj ? q.options : (DATA.labels.length ? DATA.labels : ["1", "2", "3", "4", "5"]);

    labels.forEach(function (text, i) {
      // 客观题下标 0 基；李克特 1~5。与 scoring 的约定一致，不要改。
      var value = isObj ? i : i + 1;
      var lab = el("label", "opt");
      var input = document.createElement("input");
      input.type = "radio";
      input.name = q.id;
      input.value = String(value);
      if (answers[q.id] === value) {
        input.checked = true;
        lab.classList.add("sel");
      }
      input.addEventListener("change", function () { onPick(q.id, value); });
      lab.appendChild(input);
      lab.appendChild(el("span", "lt", text));
      opts.appendChild(lab);
    });

    wrap.appendChild(opts);
    wrap.classList.toggle("blank", !(q.id in answers));
    return wrap;
  }

  function onPick(qid, value) {
    answers[qid] = value;
    save();
    var box = document.querySelector('.q[data-qid="' + qid + '"]');
    if (box) {
      box.classList.remove("blank");
      var labs = box.querySelectorAll("label.opt");
      for (var i = 0; i < labs.length; i++) labs[i].classList.remove("sel");
      var picked = box.querySelector('input[value="' + value + '"]');
      if (picked) picked.parentNode.classList.add("sel");
    }
    refresh();
  }

  function refresh() {
    var done = 0;
    for (var i = 0; i < flat.length; i++) if (flat[i] in answers) done++;
    document.getElementById("done").textContent = String(done);
    var pct = flat.length ? Math.round(done / flat.length * 100) : 0;
    document.getElementById("pct").textContent = "（" + pct + "%）";
    document.getElementById("barfill").style.width = pct + "%";
  }

  function showToast(msg) {
    var t = document.getElementById("toast");
    t.textContent = msg;
    t.classList.add("on");
    window.setTimeout(function () { t.classList.remove("on"); }, 1900);
  }

  // ---- 导出 -------------------------------------------------------------
  function orderedAnswers() {
    // 按题目顺序重排，输出文件比乱序字典好读得多
    var out = {};
    flat.forEach(function (id) { if (id in answers) out[id] = answers[id]; });
    return out;
  }

  function payloadString() {
    var body = {
      meta: {
        tool: "career-compass",
        version: /*__WB_VERSION__*/,
        created_at: new Date().toISOString().slice(0, 19),
        source: "browser-questionnaire"
      },
      answers: orderedAnswers()
    };
    return JSON.stringify(body, null, 2);
  }

  function download() {
    var blob = new Blob([payloadString()], { type: "application/json;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = EXPORT_NAME;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    showToast("已下载 " + EXPORT_NAME + "，通常在你的「下载」文件夹里");
  }

  function copy() {
    var text = payloadString();
    function fallback() {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); showToast("已复制到剪贴板"); }
      catch (e) { showToast("复制失败，请改用「导出作答文件」"); }
      document.body.removeChild(ta);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () { showToast("已复制到剪贴板"); },
        fallback
      );
    } else {
      fallback();
    }
  }

  function jumpToBlank() {
    var box = document.querySelector(".q.blank");
    if (!box) { showToast("全部答完了"); return; }
    box.scrollIntoView({ behavior: "smooth", block: "center" });
    var input = box.querySelector("input");
    if (input) input.focus({ preventScroll: true });
  }

  // ---- 启动 -------------------------------------------------------------
  document.addEventListener("DOMContentLoaded", function () {
    answers = loadSaved();
    buildForm();
    refresh();
    document.getElementById("btn-export").addEventListener("click", download);
    document.getElementById("btn-copy").addEventListener("click", copy);
    document.getElementById("btn-jump").addEventListener("click", jumpToBlank);
  });
})();
</script>
</body>
</html>
"""
