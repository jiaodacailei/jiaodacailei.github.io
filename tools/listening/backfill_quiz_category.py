# -*- coding: utf-8 -*-
"""
用法：
  python backfill_quiz_category.py docs/private/<slug>/index.html [--write]

一次性迁移脚本：给已发布、`quiz_data.json` 是用旧版 `build_vocab_quiz_data.py`
生成（词条没有 `category` 字段）的単語テスト页面，把 `category` 字段补上去，
不需要原始的 occurrences.json/authored_examples.json（这些工作文件按约定不
提交、经常已经被清理掉）。

补法：每个词条的 `sentence` 字段本来就是从"生成页面的会话/课文 tab 里抽出来
的原句"（真实出现的词）或者"人工补写的例句"（真没找到的词）两者之一——这
两种来源天生就能通过"这句话是不是逐字匹配页面上会话/课文 tab 里真实存在的
某一句"来区分，不需要原始的人工核实记录：
  - 能在"会话"tab 里找到逐字匹配的句子 → category = "dialogue"
  - 能在"课文"tab 里找到逐字匹配的句子 → category = "text"
  - 两边都找不到（人工补写的例句，本来就不是页面上任何一句的原文）→ "other"
这跟 build_vocab_quiz_data.py 里"直接读 occurrences.json 的 src"是同一个
判断依据的两种实现——那边是在数据还没生成页面之前就知道来源，这边是页面已经
生成好了、反过来从页面内容里找回这个信息，结论应该一致。

默认只是打印一份"会分到哪个分类"的预览报告，不改文件；加 `--write` 才真的
把更新后的 `category` 写回页面里 `<script id="vocab-quiz-data">` 那段 JSON、
覆盖保存这个 HTML 文件。**只改这一个 <script> 标签的内容，不碰音频、不碰
其它任何 HTML**，可以放心用 git diff 确认改动范围。已经有 `category` 字段的
词条（新脚本生成的）原样跳过，不会被这个脚本覆盖成别的值。
"""
import sys
import os
import re
import json
import argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_RT_RE = re.compile(r"<rt>[^<]*</rt>")
_TAG_RE = re.compile(r"<[^>]+>")
_SECTION_RE = re.compile(r'<section class="mondai-section[^"]*"[^>]*>(.*?)</section>', re.S)
_H2_RE = re.compile(r"<h2>([^<]*)</h2>")
_SEGJA_RE = re.compile(r'<p class="seg-ja">(.*?)</p>', re.S)
_QUIZDATA_RE = re.compile(
    r'(<script type="application/json" id="vocab-quiz-data">)(.*?)(</script>)', re.S
)


def plain_text(html_fragment):
    no_rt = _RT_RE.sub("", html_fragment)
    return _TAG_RE.sub("", no_rt).strip()


def extract_tab_sentences(html, tab_label):
    """抓某个 tab（<h2>文字精确匹配 tab_label）里全部 .seg-ja 的纯文本集合。"""
    out = set()
    for body in _SECTION_RE.findall(html):
        h2 = _H2_RE.search(body)
        if not h2 or h2.group(1).strip() != tab_label:
            continue
        for frag in _SEGJA_RE.findall(body):
            out.add(plain_text(frag))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html_path")
    ap.add_argument("--write", action="store_true", help="真的写回文件，不传就只打印预览")
    ap.add_argument("--dialogue-label", default="会话", help="会话 tab 的 <h2> 文字，默认“会话”")
    ap.add_argument("--text-label", default="课文", help="课文 tab 的 <h2> 文字，默认“课文”")
    args = ap.parse_args()

    html = open(args.html_path, encoding="utf-8").read()
    m = _QUIZDATA_RE.search(html)
    if not m:
        print("FAIL: 页面里没找到 <script id=\"vocab-quiz-data\">，这个页面没有単語テスト tab")
        sys.exit(1)

    quiz = json.loads(m.group(2))
    dialogue_sentences = extract_tab_sentences(html, args.dialogue_label)
    text_sentences = extract_tab_sentences(html, args.text_label)
    if not dialogue_sentences and not text_sentences:
        print("WARNING: 没抓到任何 %r/%r tab 的句子，"
              "检查 --dialogue-label/--text-label 是不是跟页面里 <h2> 文字对得上"
              % (args.dialogue_label, args.text_label))

    counts = {"dialogue": 0, "text": 0, "other": 0, "kept": 0}
    for entry in quiz:
        if "category" in entry:
            counts["kept"] += 1
            continue
        sent = entry.get("sentence", "")
        if sent in dialogue_sentences:
            entry["category"] = "dialogue"
            counts["dialogue"] += 1
        elif sent in text_sentences:
            entry["category"] = "text"
            counts["text"] += 1
        else:
            entry["category"] = "other"
            counts["other"] += 1

    print(f"{args.html_path}: dialogue={counts['dialogue']} text={counts['text']} "
          f"other={counts['other']} kept(已有category)={counts['kept']}")

    if not args.write:
        print("(预览模式，没有写回文件；确认分类数量看起来合理后加 --write 真正写入)")
        return

    # build_page.py 嵌入这段 <script> 时用的是 json.dumps(..., ensure_ascii=False)
    # 不带 indent（紧凑单行），这里保持同一个格式，不要 pretty-print——不然会把
    # 一行的 JSON 炸成上千行，diff 噪声爆炸，页面体积也会明显变大。
    new_json = json.dumps(quiz, ensure_ascii=False)
    new_html = html[:m.start()] + m.group(1) + new_json + m.group(3) + html[m.end():]
    open(args.html_path, "w", encoding="utf-8").write(new_html)
    print(f"wrote back to {args.html_path}")


if __name__ == "__main__":
    main()
