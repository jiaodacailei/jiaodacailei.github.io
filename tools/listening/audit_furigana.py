# -*- coding: utf-8 -*-
"""
用法：
  python audit_furigana.py <enriched.json> [<enriched2.json> ...]
  python audit_furigana.py --all <enriched.json> [<enriched2.json> ...]

人/月/日/方/上/下/中/分/時/気/家/物/目/手/口/力/名/音/色/間 这类常用单字，读音
高度依赖上下文——同一个字，独立出现/接在数字后/接在特定助词后，读音可能完全
不同（真实案例 textbook-sjp-zg-l11：「同世代の人」的"人"该读ひと，`build_page.py`
的 `ruby_html()` 靠 pykakasi 默认给出にん；「1か月」的"月"该读げつ，默认给出
がつ）。`ruby_html()` 有一张手工订正表（`_TOKEN_READING_OVERRIDES_BY_PREV`/
`_TOKEN_READING_OVERRIDES_UNCONDITIONAL`）兜底，但订正表只能"发现一个错误、
加一条"，没有主动扫描的手段——生成完页面之后，问题字不会用任何方式标出来，
只能靠人工通读整页渲染结果去认，效率很低，容易漏看（这两个字都是极常见字，
每一课都会反复出现好几次，读一遍很容易审美疲劳看走眼）。

这个脚本补上"主动扫描"这一步，但**必须严格对应 `build_page.py` 实际渲染时
读音的真实来源**，不能自己重新跑一遍 pykakasi 了事——`build_page.py` 里这一行
是关键：`ja_html = ruby_html(s["text"], rel_char_times) if rel_char_times else
s["furigana"]`，也就是说**只有带 `char_times`（会话/课文，需要跟读高亮）的
句子才会现场跑 `ruby_html()`**；**生词条目这类没有 `char_times` 的，直接用
`enriched.json` 里已经算好、存好的 `furigana` 字段**（来自 `build_vocab_from_
wordlist.py`，读音可能来自词表里人工填的 `kana` 字段，不一定是 pykakasi 默认
输出）。如果这个脚本对生词条目也无脑重新跑 pykakasi，会产生假阳性——真实
案例：生词"〜力"当初已经人工订正成读りょく存进了 `furigana` 字段，但重新跑
pykakasi 会得到默认的ちから，误报成"读音不对"，而实际页面渲染的是已经订正
过的りょく，根本没有问题。所以这个脚本区分两种情况：**有 `char_times` 的句子
——现场重跑跟 `ruby_html()` 完全同款的分词+订正表逻辑（直接 import 自
`build_page.py`，避免两边逻辑长出分歧）；没有 `char_times`、已有 `furigana`
字段的（生词表）——直接从这个字段的 `<ruby>字<rt>读音</rt></ruby>` 里正则
抠出实际读音，不重新计算**。两种情况，凡是命中"高危字表"（`DANGER_KANJI`，
**不是穷举**，遇到新的常见误读字往这里加）的字，都打印出来（句子级的带前后
一两个 token 的上下文），人工只需要扫一遍这份几十行的短报告、确认每个读音
在这句/这个词里对不对，比读整页 HTML 渲染结果快得多也准得多。

**用法建议**：`enriched.json`（会话/课文/生词，组装完、跑 `build_page.py` 之前）
都过一遍这个脚本，报告里每一条人工确认，读音不对：
  - 句子里的（有 char_times）——照 `build_page.py` 里 `_TOKEN_READING_OVERRIDES_
    BY_PREV`/`_UNCONDITIONAL` 的格式加一条订正（判断该用哪种模式见 `build_page.py`
    里两条已有注释的判断依据）。
  - 生词条目的（无 char_times，走 `furigana` 字段）——回到词表源头（`vocab_words.
    json`）给这一条加/改 `kana` 字段，重新跑 `build_vocab_from_wordlist.py`。
这个脚本**只负责发现疑似读音问题、不判断对错、不负责自动修**——报告里每一条
都要人工用自己的日语知识核对，不能假设"命中高危字表=一定是错的"。

## `--all`：全量读音复核（不限于高危字表，真正的人工全审）

`DANGER_KANJI` 这张表本身也有天花板——只能覆盖"已经在某次真实案例里踩过坑
的字"，专有名词（人名/地名/作品名）这类读音完全没有通用规律可循、必须靠
具体知识判断的情况，天生就不可能靠"哪个字危险"这种模式列表覆盖到。真实
案例（textbook-sjp-zg-l11）：《千と千尋の神隠し》（《千与千寻》）这句话
里的人名"千尋"被 pykakasi 按通用音读猜成せんじん（该读ちひろ），"尋"这个
字根本不在 `DANGER_KANJI` 里，默认扫描完全不会命中、不会被提醒复核——
这类 bug 只有把**全部**假名注音（不只是命中高危字表的）都过一遍、每一条
都用自己的日语知识判断，才能发现。加 `--all` 参数即可切换到这个模式：
不再按 `DANGER_KANJI` 过滤，打印这份 `enriched.json` 里**每一个**带汉字的
读音（句子级的带完整原句上下文，生词级的带词条本身），供逐条人工全审。
一课通常一两百条，一次性读完可行，读的时候优先留意：人名/地名/作品名这类
专有名词（读音没有规律可循，必须凭知识判断）、同一个字/同一个词在这一课
不同地方读音是否前后矛盾（比如同一课里两条生词都叫"その後"却读音不一样，
这种不一致本身就值得停下来确认是不是有问题，即使两个读音单独看都不算错）。
"""
import sys
import os
import re
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_page import (
    _kks,
    _TOKEN_READING_OVERRIDES_BY_PREV,
    _TOKEN_READING_OVERRIDES_UNCONDITIONAL,
    _resolve_hira,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 不是穷举——这些是最常见的"训读/音读/量词读音"随上下文剧烈变化的单字，
# 每一课教材几乎都会反复出现，遇到新的常见误读字（发现方式：人工听音频/读
# 已知正确翻译时觉得读音不对）就往这里加。
DANGER_KANJI = set("人月日方上下中分時気家物目手口力名音色間位歳君")

_RUBY_RE = re.compile(r"<ruby>([^<]+)<rt>([^<]+)</rt></ruby>")


def _has_kanji(s):
    return any("一" <= ch <= "鿿" for ch in s)


def _scan_live_text(text, show_all):
    """有 char_times 的句子——build_page.py 现场跑 ruby_html()，这里重现同一套
    分词+订正表逻辑（不是重新发明一套，直接复用 build_page.py 的表和 _kks）。"""
    hits = []
    for line in text.split("\n"):
        tokens = _kks.convert(line)
        prev_orig = None
        row = []
        for i, t in enumerate(tokens):
            orig = t["orig"]
            hira = t["hira"]
            overridden = False
            if orig in _TOKEN_READING_OVERRIDES_UNCONDITIONAL:
                hira = _TOKEN_READING_OVERRIDES_UNCONDITIONAL[orig]
                overridden = True
            elif (prev_orig, orig) in _TOKEN_READING_OVERRIDES_BY_PREV:
                hira = _TOKEN_READING_OVERRIDES_BY_PREV[(prev_orig, orig)]
                overridden = True
            else:
                new_hira = _resolve_hira(orig, hira, prev_orig)
                if new_hira != hira:
                    hira = new_hira
                    overridden = True
            if show_all:
                if _has_kanji(orig) and hira != orig:
                    row.append(f"{orig}[{hira}]")
            elif any(ch in DANGER_KANJI for ch in orig):
                before = tokens[i - 1]["orig"] if i > 0 else ""
                after = tokens[i + 1]["orig"] if i + 1 < len(tokens) else ""
                tag = " (订正表已生效)" if overridden else ""
                hits.append(f"...{before}[{orig}→{hira}]{after}...{tag}")
            prev_orig = orig
        if show_all and row:
            hits.append(" ".join(row) + f"   full=「{line}」")
    return hits


def _scan_prebaked_furigana(furigana_html, show_all, word_text=None):
    """没有 char_times 的（生词表）——build_page.py 直接用这个字段，不重新
    计算，读音真实来源可能是词表里人工填的 kana，不是 pykakasi 默认输出。"""
    hits = []
    pairs = _RUBY_RE.findall(furigana_html or "")
    if show_all:
        if pairs:
            row = " ".join(f"{o}[{h}]" for o, h in pairs)
            hits.append(f"(vocab {word_text!r}): {row}")
        return hits
    for orig, hira in pairs:
        if any(ch in DANGER_KANJI for ch in orig):
            hits.append(f"[{orig}→{hira}] (生词表 furigana 字段)")
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("enriched_json", nargs="+")
    ap.add_argument("--all", action="store_true",
                     help="不按 DANGER_KANJI 过滤，打印全部带汉字的读音，供逐条人工全审")
    args = ap.parse_args()

    total = 0
    for path in args.enriched_json:
        data = json.load(open(path, encoding="utf-8"))
        print(f"=== {path} ===")
        for s in sorted(data["sentences"], key=lambda s: s["id"]):
            if s.get("char_times"):
                hits = _scan_live_text(s["text"], args.all)
            else:
                hits = _scan_prebaked_furigana(s.get("furigana"), args.all, s.get("text"))
            for h in hits:
                total += 1
                print(f"  #{s['id']}: {h}")

    label = "处带汉字的读音，逐条用日语知识确认（人名/地名/作品名等专有名词、" \
            "同一个字/词在本课内前后读音是否一致，尤其要留意）" if args.all \
            else "处高危字命中，逐条人工确认读音是否符合这句/这个词的实际语境"
    print(f"\n共 {total} {label}")


if __name__ == "__main__":
    main()
