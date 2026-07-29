# -*- coding: utf-8 -*-
"""
用法：
  python verify_blank_answers.py docs/private/<slug>/index.html

"填空"练习模式挖哪几个空、正确答案是什么，来自每句的 `blanks` 字段（内容
作者直接写这句原文里要挖空的具体文字，比如 `["映画にしても音楽にしても"]`）
——不是从 `notes` 文字里用正则猜「...」引号内容当挖空目标（那种做法猜不出
两类场景：notes 写抽象占位字母比如"AでもBでも"、notes 引用词典型但句子里是
活用形，而且猜错了没有任何报错，只有打开填空模式点开才会发现，这个 skill
早期版本踩过这个坑，见 SKILL.md 里的相关记录）。

`blanks` 现在是显式数据，出问题只可能是一种情况：写的时候打错字/漏字，
导致这段文字在这句原文里根本找不到（`listening-page.js` 里 `plain.indexOf
(text) === -1`，控制台会报 warning，但用户不会主动去看控制台，这个空就会
在填空模式里悄无声息地消失，不会显式报错）。这个脚本批量检查每句 `blanks`
里每一条是不是这句原文（假名注音已去掉的纯文本）的真实子串，生成/手改完
`blanks` 字段之后跑一遍，不用打开浏览器逐句核对。

**两种页面结构都支持**：
- data-driven 页面（`--data-driven` 生成，或者用 migrate_to_data_driven.py
  迁移过的）——内容在同目录的 `data.js` 里，直接读 `window.LESSON_DATA.tabs
  [].questions[].sentences[]`，每句的纯文本从 `tokens` 数组拼出来，不用碰
  HTML、也不用正则解析。
- 旧式页面（内容直接烘焙进 index.html）——`blanks` 体现为每张 `.seg-card`
  的 `data-blanks` 属性，纯文本从 `.seg-ja` 的 innerHTML 里剥掉 `<rt>` 标签
  拿到，走原来的 HTML 正则解析路径。

只报告，不改文件——`blanks` 打错了应该由人决定改成什么（是这句原文里哪一
段），脚本没法替你判断意图。
"""
import sys
import os
import re
import json
import html as html_mod
import argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_CARD_RE = re.compile(
    r'<div class="seg-card[^"]*" id="(card-a\d+)"(?:\s+data-blanks="([^"]*)")?[^>]*>.*?'
    r'<p class="seg-ja">(.*?)</p>',
    re.S,
)
_RT_RE = re.compile(r"<rt>.*?</rt>")
_TAG_RE = re.compile(r"<[^>]+>")


def plain_text(inner_html):
    """去掉 <rt>...</rt>（假名注音），剩下的标签也剥掉，只留纯文本——
    跟 listening-page.js 的 plainTextOf 是同一个逻辑。"""
    s = _RT_RE.sub("", inner_html)
    s = _TAG_RE.sub("", s)
    return html_mod.unescape(s)


def check_data_driven(data_js_path):
    raw = open(data_js_path, encoding="utf-8").read()
    raw = raw[raw.index("{"):raw.rindex("}") + 1]
    data = json.loads(raw)

    total_sentences = 0
    total_with_blanks = 0
    total_blanks = 0
    flagged = []
    for tab in data.get("tabs", []):
        for q in tab.get("questions", []):
            for s in q.get("sentences", []):
                total_sentences += 1
                blanks = s.get("blanks") or []
                if not blanks:
                    continue
                total_with_blanks += 1
                plain = "".join(t["text"] for t in s.get("tokens", []))
                for text in blanks:
                    total_blanks += 1
                    if text not in plain:
                        flagged.append((f"card-a{s['id']}", text, plain))
    return total_sentences, total_with_blanks, total_blanks, flagged


def check_legacy_html(html_path):
    html = open(html_path, encoding="utf-8").read()
    cards = _CARD_RE.findall(html)
    if not cards:
        print("FAIL: 没找到任何 seg-card，检查文件路径/HTML 结构是否符合预期")
        sys.exit(1)

    total_with_blanks = 0
    total_blanks = 0
    flagged = []
    for card_id, blanks_attr, seg_ja_html in cards:
        if not blanks_attr:
            continue
        try:
            blanks = json.loads(html_mod.unescape(blanks_attr))
        except ValueError:
            flagged.append((card_id, "(JSON 解析失败)", blanks_attr))
            continue
        total_with_blanks += 1
        plain = plain_text(seg_ja_html)
        for text in blanks:
            total_blanks += 1
            if text not in plain:
                flagged.append((card_id, text, plain))
    return len(cards), total_with_blanks, total_blanks, flagged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html_path")
    args = ap.parse_args()

    data_js_path = os.path.join(os.path.dirname(args.html_path), "data.js")
    if os.path.exists(data_js_path):
        print(f"(检测到 {data_js_path}，按 data-driven 页面校验)")
        total, total_with_blanks, total_blanks, flagged = check_data_driven(data_js_path)
    else:
        total, total_with_blanks, total_blanks, flagged = check_legacy_html(args.html_path)

    print(f"{args.html_path}: {total} 句，{total_with_blanks} 句有 blanks，共 {total_blanks} 个空")
    if not flagged:
        print("OK: 每个 blanks 条目都是对应句子原文的真实子串")
        return
    print(f"\n{len(flagged)} 个 blanks 条目在原文里找不到，检查是不是打错字了：")
    for card_id, text, plain in flagged:
        print(f"  {card_id}: blanks 写的是「{text}」，这句原文是「{plain}」")
    sys.exit(1)


if __name__ == "__main__":
    main()
