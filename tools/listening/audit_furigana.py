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

这个脚本补上"主动扫描"这一步，但**必须严格对应 `build_page.py --data-driven`
实际渲染时读音的真实来源**，不能自己重新跑一遍 pykakasi 了事，也不能相信
`enriched.json` 里存的旧字段——`build_page.py` 的 `sentence_to_data()`（`--data-
driven` 页面，也就是这个 skill 唯一用的路径）判断逻辑是：**有 `char_times`
（会话/课文）——现场跑 `tokenize_ja(text, rel_char_times)`；没有 `char_times`
但有 `kana` 字段（生词条目人工填过读音）——现场跑 `_split_kana_segments(text,
kana)`；两者都没有——现场跑 `tokenize_ja(text)`（自动分词+订正表，没有跟读
时间戳）**。**三种情况全部是"现场重新计算"，没有一种是直接读 `enriched.json`
里存的 `furigana` 字段**——这个字段是更早期非 `--data-driven` 页面路径
（`sentence_card_html()`）的产物，`--data-driven` 模式下 `build_page.py` 根本
不读它。

**这个脚本早期版本对生词条目走的是第四种逻辑：直接读 `furigana` 字段**（当
时这个假设是对的，非 `--data-driven` 页面确实这样渲染）——`--data-driven`
成为这个 skill 唯一用法之后，这个分支没有跟着更新，一直读一个渲染时根本
用不到的字段，长期处于"看起来在审核、实际零覆盖"的状态，直到真实案例
（textbook-sjp-zg-l14，"茶色い"）才暴露：这一课的生词表用的是"整段word-
level转写+一次性`align_group()`对齐"这套自定义流程（`SKILL.md`"生词边界
收紧"一节），从不调用 `build_vocab_from_wordlist.py`，从来没有填过
`furigana` 字段——**88个生词条目的 `furigana` 全部是 `None`**，这个脚本
（包括 `--all` 全量模式）对整个生词表的每一条都只返回空结果，报告里干净
得像是"审过了、没问题"，实际上是**一整个 tab 从来没有被真正检查过**，
"茶色い"读音被 `_split_kana_segments()` 内部的一个 mora 计数 bug 截断成
"ちゃ"，从生成到用户发现之间的所有轮次"全量读音复核"全部没能发现——不是
读漏了，是压根没读到任何数据。**即使 `furigana` 字段确实被填过的课
（走标准 `build_vocab_from_wordlist.py` 流程的），这个字段也只是构建生词表
那一刻的快照，跟 `sentence_to_data()` 真正现场调用的计算结果不保证一致**
（比如后续任何一次给 `_split_kana_segments()`/`_resolve_hira()` 的订正规则
改动，`furigana` 字段都不会跟着重算），本质上都是"审核的不是实际渲染出来
的东西"这同一个问题，只是 l14 这次因为字段整体缺失而 100% 暴露。现在
已改成跟句子分支一样"现场按 `sentence_to_data()` 的真实分支重新计算"，
不再读这个字段（`_scan_vocab_entry()`）。

**用法建议**：`enriched.json`（会话/课文/生词，组装完、跑 `build_page.py` 之前）
都过一遍这个脚本，报告里每一条人工确认，读音不对：
  - 句子里的（有 char_times）——照 `build_page.py` 里 `_TOKEN_READING_OVERRIDES_
    BY_PREV`/`_UNCONDITIONAL` 的格式加一条订正（判断该用哪种模式见 `build_page.py`
    里两条已有注释的判断依据）。
  - 生词条目的（无 char_times）——有 `kana` 字段的回到词表源头改 `kana`；没有
    `kana` 字段、走自动分词的，同句子分支一样加订正表条目。
这个脚本**只负责发现疑似读音问题、不判断对错、不负责自动修**——报告里每一条
都要人工用自己的日语知识核对，不能假设"命中高危字表=一定是错的"，**更不能
假设"这个脚本对某个 tab 完全没输出=这个 tab 没问题"——先确认这个 tab 的条目
真的被这个脚本处理过（比如临时加一行 print 数一下处理了多少条），再信任
"零命中"这个结论**。

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
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_page import (
    _kks,
    _TOKEN_READING_OVERRIDES_BY_PREV,
    _TOKEN_READING_OVERRIDES_UNCONDITIONAL,
    _resolve_hira,
    _split_kana_segments,
    _needs_kana_annotation,
    _sudachi_line_tokens,
    _sudachi_reading_for_span,
    tokenize_ja,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 不是穷举——这些是最常见的"训读/音读/量词读音"随上下文剧烈变化的单字，
# 每一课教材几乎都会反复出现，遇到新的常见误读字（发现方式：人工听音频/读
# 已知正确翻译时觉得读音不对）就往这里加。
DANGER_KANJI = set("人月日方上下中分時気家物目手口力名音色間位歳君後次")


def _has_kanji(s):
    return any("一" <= ch <= "鿿" for ch in s)


def _scan_live_text(text, show_all, vocab_readings=None):
    """有 char_times 的句子——build_page.py 现场跑 tokenize_ja()，这里重现同一套
    分词+订正表逻辑（不是重新发明一套，直接复用 build_page.py 的表和 _kks）。
    `vocab_readings` 见 `tokenize_ja()` 文档字符串——跟真实渲染路径一样，检查
    优先级放在 `_TOKEN_READING_OVERRIDES_*`/`_resolve_hira` 之前。"""
    hits = []
    for line in text.split("\n"):
        tokens = _kks.convert(line)
        sudachi_tokens = _sudachi_line_tokens(line)
        prev_orig = None
        prev2_orig = None
        line_offset = 0
        row = []
        for i, t in enumerate(tokens):
            orig = t["orig"]
            hira = t["hira"]
            tok_len = len(orig)
            tok_start = line_offset
            # 跟 build_page.py 的 tokenize_ja() 用同一条 next_char 计算方式——
            # 有些订正规则（比如"後にして"这个惯用语）要看这个 token 后面紧跟
            # 的原文字符才能判断，不传 next_char 会导致这类规则在这个审核脚本
            # 里显示成"没生效"，误导人工复核（规则在真正生成页面时是生效的，
            # 只是这个复现逻辑漏传了这个参数）。
            next_char = line[line_offset + tok_len] if line_offset + tok_len < len(line) else ""
            line_offset += tok_len
            overridden = False
            if vocab_readings and orig in vocab_readings:
                hira = vocab_readings[orig]
                overridden = True
            elif (prev_orig, orig) in _TOKEN_READING_OVERRIDES_BY_PREV:
                # 跟 build_page.py 的 tokenize_ja() 同一顺序：BY_PREV 先于
                # UNCONDITIONAL 检查（"君"同时在两张表里，UNCONDITIONAL 先
                # 命中的话 BY_PREV 永远轮不到）。
                hira = _TOKEN_READING_OVERRIDES_BY_PREV[(prev_orig, orig)]
                overridden = True
            elif orig in _TOKEN_READING_OVERRIDES_UNCONDITIONAL:
                hira = _TOKEN_READING_OVERRIDES_UNCONDITIONAL[orig]
                overridden = True
            else:
                new_hira = _resolve_hira(orig, hira, prev_orig, next_char, prev2_orig)
                if new_hira is not None:
                    # 用 `is not None` 而不是"new_hira != hira"判断命中与否——
                    # 后者会把"规则命中、但答案恰好和 pykakasi 自己的默认猜测
                    # 一样"误判成"没命中"，见 build_page.py 里 `_resolve_hira()`
                    # "N本"那条规则的说明，跟 tokenize_ja() 保持同一份判断逻辑。
                    hira = new_hira
                    overridden = True
                else:
                    # 跟 tokenize_ja() 同一条 SudachiPy 交叉核对兜底——只在
                    # pykakasi 的原始猜测没被任何手写规则改过时才生效，见
                    # build_page.py 里 `_sudachi_reading_for_span()` 上方的
                    # 详细说明。这一步漏做的话，审核报告会显示 pykakasi 的
                    # 原始（可能错误的）读音，但页面真正渲染时其实已经被
                    # SudachiPy 交叉核对纠正过了——误导人工复核，让人以为
                    # 这里有问题去手动加订正表，实际已经自动修好了。
                    sudachi_hira = _sudachi_reading_for_span(sudachi_tokens, tok_start, tok_start + tok_len)
                    if sudachi_hira and sudachi_hira != hira:
                        hira = sudachi_hira
                        overridden = True
            if show_all:
                if _has_kanji(orig) and hira != orig:
                    row.append(f"{orig}[{hira}]")
            elif any(ch in DANGER_KANJI for ch in orig):
                before = tokens[i - 1]["orig"] if i > 0 else ""
                after = tokens[i + 1]["orig"] if i + 1 < len(tokens) else ""
                tag = " (订正表已生效)" if overridden else ""
                hits.append(f"...{before}[{orig}→{hira}]{after}...{tag}")
            prev2_orig = prev_orig
            prev_orig = orig
        if show_all and row:
            hits.append(" ".join(row) + f"   full=「{line}」")
    return hits


def _scan_vocab_entry(s, show_all):
    """没有 char_times 的（生词表）——严格复现 sentence_to_data() 的真实分支：
    有 `kana` 字段（人工填过读音）就跑 `_split_kana_segments(text, kana)`，
    没有就跑 `tokenize_ja(text)`（自动分词+订正表，跟句子分支同款逻辑，只是
    没有 char_times 所以不产出跟读时间戳）——两条分支都是"现场重新计算"，
    不读 `enriched.json` 里可能存在也可能是 None、且不保证跟当前 build_page.py
    逻辑一致的 `furigana` 字段（历史教训见文件头部文档字符串）。"""
    text = s.get("text", "")
    if not text:
        return []
    kana = s.get("kana")
    if kana and _needs_kana_annotation(text) and kana != text:
        tokens = _split_kana_segments(text, kana)
    elif kana:
        tokens = [{"text": text}]
    else:
        tokens = tokenize_ja(text)
    pairs = [(t["text"], t["kana"]) for t in tokens if t.get("kana")]
    if show_all:
        if pairs:
            row = " ".join(f"{o}[{h}]" for o, h in pairs)
            return [f"(vocab {text!r}): {row}"]
        return []
    hits = []
    for orig, hira in pairs:
        if any(ch in DANGER_KANJI for ch in orig):
            hits.append(f"[{orig}→{hira}] (生词表)")
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("enriched_json", nargs="+")
    ap.add_argument("--all", action="store_true",
                     help="不按 DANGER_KANJI 过滤，打印全部带汉字的读音，供逐条人工全审")
    args = ap.parse_args()

    total = 0
    sentence_count = 0
    vocab_count = 0
    for path in args.enriched_json:
        data = json.load(open(path, encoding="utf-8"))
        # 跟 build_lesson_data() 的 vocab_readings 构造方式完全一致——只收有
        # kana 字段的生词条目，见 tokenize_ja() 文档字符串。
        vocab_readings = {
            s["text"]: s["kana"]
            for s in data["sentences"]
            if not s.get("char_times") and s.get("kana")
        }
        print(f"=== {path} ===")
        for s in sorted(data["sentences"], key=lambda s: s["id"]):
            if s.get("char_times"):
                sentence_count += 1
                hits = _scan_live_text(s["text"], args.all, vocab_readings)
            else:
                vocab_count += 1
                hits = _scan_vocab_entry(s, args.all)
            for h in hits:
                total += 1
                print(f"  #{s['id']}: {h}")

    label = "处带汉字的读音，逐条用日语知识确认（人名/地名/作品名等专有名词、" \
            "同一个字/词在本课内前后读音是否一致，尤其要留意）" if args.all \
            else "处高危字命中，逐条人工确认读音是否符合这句/这个词的实际语境"
    print(f"\n共 {total} {label}")
    # 覆盖计数——不能只看上面的命中数就信"没问题"，先确认这两类条目真的都
    # 被处理过（历史教训：曾经生词表 furigana 字段整体缺失，脚本对88个生词
    # 条目全部返回空结果，报告"干净"得跟真的审过一样，见文件头部文档字符串）。
    print(f"（本次共处理 {sentence_count} 句 + {vocab_count} 条生词——如果某个 tab "
          f"理应有内容但这里的数字是0，先查是不是传错了文件，不要直接信任"
          f"上面的命中数）")


if __name__ == "__main__":
    main()
