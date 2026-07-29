# -*- coding: utf-8 -*-
"""
用法：
  python verify_blank_answers.py docs/private/<slug>/index.html

"填空"练习模式挖哪几个空、正确答案是什么，来自每张卡片自己的 `data-blanks`
属性（`build_page.py` 按 sentence 的 `blanks` 字段生成，内容作者直接写这句
原文里要挖空的具体文字，比如 `["映画にしても音楽にしても"]`）——不再像
最早的版本那样从 `seg-notes` 文字里用正则猜「...」引号内容当挖空目标（那种
做法猜不出两类场景：notes 写抽象占位字母比如"AでもBでも"、notes 引用词典型
但句子里是活用形，而且猜错了没有任何报错，只有打开填空模式点开才会发现）。

`data-blanks` 现在是显式数据，出问题只可能是一种情况：写的时候打错字/漏字，
导致这段文字在这句原文里根本找不到（`listening-page.js` 里 `plain.indexOf
(text) === -1`，控制台会报 warning，但用户不会主动去看控制台，这个空就会
在填空模式里悄无声息地消失，不会显式报错）。这个脚本批量检查每张卡片的
`data-blanks` 里每一条是不是这句 `seg-ja` 纯文本（假名注音已去掉）的真实
子串，生成/手改完 `blanks` 字段之后跑一遍，不用打开浏览器逐句核对。

只报告，不改文件——`data-blanks` 打错了应该由人决定改成什么（是这句原文里
哪一段），脚本没法替你判断意图。
"""
import sys
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html_path")
    args = ap.parse_args()

    html = open(args.html_path, encoding="utf-8").read()
    cards = _CARD_RE.findall(html)
    if not cards:
        print("FAIL: 没找到任何 seg-card，检查文件路径/HTML 结构是否符合预期")
        sys.exit(1)

    total_cards_with_blanks = 0
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
        total_cards_with_blanks += 1
        plain = plain_text(seg_ja_html)
        for text in blanks:
            total_blanks += 1
            if text not in plain:
                flagged.append((card_id, text, plain))

    print(f"{args.html_path}: {len(cards)} 张卡片，{total_cards_with_blanks} 张有 "
          f"data-blanks，共 {total_blanks} 个空")
    if not flagged:
        print("OK: 每个 data-blanks 条目都是对应句子原文的真实子串")
        return
    print(f"\n{len(flagged)} 个 data-blanks 条目在原文里找不到，检查是不是打错字了："
    )
    for card_id, text, plain in flagged:
        print(f"  {card_id}: data-blanks 写的是「{text}」，这句原文是「{plain}」")
    sys.exit(1)


if __name__ == "__main__":
    main()
