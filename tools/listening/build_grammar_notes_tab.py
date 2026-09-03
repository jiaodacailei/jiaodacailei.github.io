# -*- coding: utf-8 -*-
"""用法：
  python build_grammar_notes_tab.py <data.js路径> <content模块.py路径>

把教材配套app自己的"语法与表达"tab内容（截图转录）拼成 data.js 能吃的
tab结构，插到"课文"和"生词"之间（跟教材app自己的tab顺序一致：会话|课文|
语法与表达|生词|練習）——`jp-textbook-lesson` skill 的可选扩展步骤，只在
这一课的素材目录里确实有"语法与表达/{会话,课文}"截图时才需要跑，源头案例
见 SKILL.md 的 l17 条目。

<content模块.py>：跟这个脚本同目录规则无关，用 --content-path 指定的任意
.py 文件，必须定义两个模块级变量：
  KAISHIWA = [(卡片标题, 中文讲解正文, [(日语例句, 中文翻译), ...]), ...]
  KEWEN    = 同上，对应"课文"分组
卡片标题："称赞・谦虚"这类不带编号的专题卡，或"1. 省略主语"这类编号语法点；
中文讲解正文可以用\\n\\n分段（前端 .q-overview 已经是 white-space: pre-line）；
例句允许空列表（比如纯词汇罗列的"词语之窗"类专题卡)。

例句音频/跟读时间戳：能在现有"会话"/"课文" tab 里精确文字匹配上的句子
（原文一字不差），直接复用那句的 tokens/audio（含char_times，真人朗读+
faster-whisper对齐）；匹配不上的（本课对话/课文里没出现过的补充例句）只做
`tokenize_ja()` 假名注音，不配音频（audio=null）——默写/跟读这两个依赖音频
的模式对这些句子自然不可用，填空/纯阅读不受影响。以后要给这批例句也配上
音频，思路是另起一个跟 build_exam_audio.py 一样的 edge-tts+faster-whisper
批量合成脚本，对 audio 为 null 的句子补跑一遍。
"""
import sys
import os
import re
import json
import argparse
import importlib.util

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_page import tokenize_ja  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def load_content(path):
    spec = importlib.util.spec_from_file_location("grammar_notes_content", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.KAISHIWA, mod.KEWEN


def load_data(data_js_path):
    raw = open(data_js_path, encoding="utf-8").read()
    prefix = raw[: raw.index("{")]
    body = raw[raw.index("{") :]
    body = re.sub(r";\s*$", "", body.strip())
    data = json.loads(body)
    if any(t["mondai"] == "语法与表达" for t in data["tabs"]):
        raise SystemExit(
            "data.js 里已经有“语法与表达”tab 了——重复跑会再插入一份、"
            "id 也会跟已有的撞车。如果是想改内容，直接手改 data.js 或者先手动"
            "删掉这个tab再重跑，不要对着已经合并过的文件再跑一次这个脚本。"
        )
    return prefix, data


def build_lookup(data):
    lookup = {}
    for tab in data["tabs"]:
        if tab["mondai"] not in ("会话", "课文"):
            continue
        for q in tab["questions"]:
            for s in q["sentences"]:
                text = "".join(t["text"] for t in s["tokens"] if t.get("text") != "\n")
                lookup[text] = s
    return lookup


def next_id_counter(data):
    max_id = 0
    for tab in data["tabs"]:
        for q in tab["questions"]:
            for s in q["sentences"]:
                max_id = max(max_id, s["id"])
    n = [max_id]

    def nxt():
        n[0] += 1
        return n[0]

    return nxt


def make_sentence(ja, zh, lookup, next_id):
    matched = lookup.get(ja)
    sid = next_id()
    if matched:
        return {
            "id": sid,
            "speaker": None,
            "speakerKana": None,
            "tokens": matched["tokens"],
            "zh": zh,
            "notes": "",
            "blanks": [],
            "audio": matched.get("audio"),
        }, True
    tokens = tokenize_ja(ja)
    return {
        "id": sid,
        "speaker": None,
        "speakerKana": None,
        "tokens": tokens,
        "zh": zh,
        "notes": "",
        "blanks": [],
        "audio": None,
    }, False


def build_group(cards, lookup, next_id, stats):
    questions = []
    for title, overview, examples in cards:
        sentences = []
        for ja, zh in examples:
            s, matched = make_sentence(ja, zh, lookup, next_id)
            sentences.append(s)
            stats["matched" if matched else "new"] += 1
        questions.append({"question": title, "overview": overview, "answer": "", "sentences": sentences})
    return questions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_js")
    ap.add_argument("content_path")
    args = ap.parse_args()

    kaishiwa, kewen = load_content(args.content_path)
    prefix, data = load_data(args.data_js)
    lookup = build_lookup(data)
    next_id = next_id_counter(data)

    stats = {"matched": 0, "new": 0}
    questions = []
    questions.append({"question": "会话", "overview": "", "answer": "", "sentences": []})
    questions.extend(build_group(kaishiwa, lookup, next_id, stats))
    questions.append({"question": "课文", "overview": "", "answer": "", "sentences": []})
    questions.extend(build_group(kewen, lookup, next_id, stats))

    grammar_tab = {"mondai": "语法与表达", "questions": questions}

    idx = next(i for i, t in enumerate(data["tabs"]) if t["mondai"] == "生词")
    data["tabs"].insert(idx, grammar_tab)

    out = prefix + json.dumps(data, ensure_ascii=False, indent=2) + ";\n"
    with open(args.data_js, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)

    print("matched (reused audio):", stats["matched"])
    print("new (no audio, tokenize_ja only):", stats["new"])
    print("wrote", args.data_js)


if __name__ == "__main__":
    main()
