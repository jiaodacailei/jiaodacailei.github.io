# -*- coding: utf-8 -*-
"""
用法：
  python verify_blank_answers.py docs/private/<slug>/index.html

复刻 listening-page.js 里"填空"练习模式的挖空逻辑（extractGrammarQueries/
findBlankRange/token 级挖空+裁切），在生成页面之后不用真的打开浏览器逐句
点开填空模式，就能看到每句 seg-notes 里的「...」语法点最终会被挖出哪段
文字、对应的"正确答案"是什么——直接打印报告，人工过一遍就能发现内容
问题（笔记引用的词根本没出现在句子里、或者只匹配上了词根前几个字符）。

真实案例（textbook-sjp-zg-l11 card-a12）：seg-notes 引用了「〜というわけ
ではない」，但这句里"というわけではない"前后紧贴着的文字（"があ る"/
"んですね"）被分词器粘成了同一个不可再分的假名 token，挖空逻辑一开始
是"只要 range 命中了这个 token 的一部分，就把整个 token 都挖空"，导致
真正生成的"正确答案"变成了"があるというわけではないんですね"（16个字，
比语法点本身多出7个字），用户对着 notes 打"というわけではない"永远判错。
这个 bug 已经在 listening-page.js 里通过"token 级裁切"修好了（挖空范围
精确对齐 range 边界，跨 token 的首尾只留 range 内的那一截），但这类问题
不会在生成时自动报错、只有真的打开填空模式点开对应句子才会发现——这个
脚本就是把"点开每一句填空模式"这件事自动化、批量跑一遍，生成之后过一遍
报告比手工挨句点快得多。

**这个脚本是 listening-page.js 里同一段逻辑的 Python 移植**，两边必须保持
同步——JS 那边如果改了 extractGrammarQueries/findBlankRange/挖空裁切的
算法，这个脚本也要跟着改，否则报告会跟浏览器里的真实行为对不上。移植内容
仅限于"计算每个语法点最终会挖出什么答案"，不移植 UI 交互（判分/自动跳转
这些，那些不影响"答案文本是什么"这个问题）。

只报告，不改文件——挖空范围本来就是从句子原文里正确抠出来的，没有"自动
修正"的余地。如果报告里某个语法点没有精确匹配的挖空答案，需要人工判断：
是笔记写得需要调整（比如把笔记里的词典型换成句子里实际出现的活用形），
还是可以接受（比如笔记顺带解释了词典型，只是没打算单独出一道题——这种
情况下这句实际挖出的其它答案里通常能看到那个词的活用形）。
"""
import sys
import re
import html as html_mod
import argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_CARD_RE = re.compile(
    r'<div class="seg-card[^"]*" id="(card-a\d+)">.*?'
    r'<p class="seg-ja">(.*?)</p>.*?'
    r'(?:<div class="seg-notes">(.*?)</div>)?\s*<audio',
    re.S,
)
_PIECE_RE = re.compile(r'<span class="tw" data-t="[\d.]+">(.*?)</span>|(<br\s*/?>)|([^<]+)')
_RT_RE = re.compile(r"<rt>.*?</rt>")
_TAG_RE = re.compile(r"<[^>]+>")
_QUERY_RE = re.compile(r"「([^」]+)」")
_LEADING_WAVE_RE = re.compile(r"^[~〜]+")
_TRAILING_NONWORD_RE = re.compile(r"[^\w々ー]+$")


def plain_text(inner_html):
    """跟 JS 的 plainTextOf 一样：去掉 <rt>...</rt>，剩下的标签也剥掉，只留纯文本。"""
    s = _RT_RE.sub("", inner_html)
    s = _TAG_RE.sub("", s)
    return html_mod.unescape(s)


def tokenize(seg_ja_html):
    """跟 JS 的 baseTokens 一样：按 .tw span / 裸文本切成 (start, end, text) 列表。"""
    tokens = []
    offset = 0
    for m in _PIECE_RE.finditer(seg_ja_html):
        span_inner, br, bare_text = m.group(1), m.group(2), m.group(3)
        if span_inner is not None:
            text = plain_text(span_inner)
        elif br is not None:
            text = "\n"
        else:
            text = html_mod.unescape(bare_text)
        if not text:
            continue
        tokens.append({"start": offset, "end": offset + len(text), "text": text})
        offset += len(text)
    return tokens


def extract_queries(notes_text):
    out = []
    for m in _QUERY_RE.finditer(notes_text):
        q = _LEADING_WAVE_RE.sub("", m.group(1))
        q = _TRAILING_NONWORD_RE.sub("", q)
        if len(q) >= 2:
            out.append(q)
    return out


def find_blank_range(plain, query):
    for length in range(len(query), 1, -1):
        idx = plain.find(query[:length])
        if idx != -1:
            return (idx, idx + length)
    return None


def compute_blanks(seg_ja_html, notes_html):
    tokens = tokenize(seg_ja_html)
    plain = "".join(t["text"] for t in tokens)
    notes_text = plain_text(notes_html) if notes_html else ""
    queries = extract_queries(notes_text)
    if not queries:
        return [], queries

    ranges = []
    for q in queries:
        r = find_blank_range(plain, q)
        if r:
            ranges.append(r)
    # 只按 start 排序（JS 是 ranges.sort((a,b)=>a.start-b.start)，稳定排序，
    # start 相同时保留原始插入顺序）——不能直接对 (start,end) 元组整体排序，
    # Python 元组比较在 start 相同时会退回去比 end，跟 JS 的排序结果不一样，
    # start 相同时谁排在前面会影响下面"重叠就丢弃"这一步保留的是哪个 range。
    ranges.sort(key=lambda r: r[0])
    filtered = []
    for r in ranges:
        if not filtered or r[0] >= filtered[-1][1]:
            filtered.append(r)

    results = []
    consumed = set()
    for start, end in filtered:
        overlapping = [
            (i, t) for i, t in enumerate(tokens)
            if t["start"] < end and t["end"] > start and i not in consumed
        ]
        if not overlapping:
            continue
        consumed.update(i for i, _t in overlapping)
        answer = "".join(
            t["text"][max(t["start"], start) - t["start"]: min(t["end"], end) - t["start"]]
            for _i, t in overlapping
        )
        results.append((start, end, answer))
    return results, queries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html_path")
    args = ap.parse_args()

    html = open(args.html_path, encoding="utf-8").read()
    cards = _CARD_RE.findall(html)
    if not cards:
        print("FAIL: 没找到任何 seg-card，检查文件路径/HTML 结构是否符合预期")
        sys.exit(1)

    total_queries = 0
    total_blanked = 0
    flagged = []
    for card_id, seg_ja_html, notes_html in cards:
        if not notes_html:
            continue
        blanks, queries = compute_blanks(seg_ja_html, notes_html)
        total_queries += len(queries)
        total_blanked += len(blanks)
        matched_answers = {a for _s, _e, a in blanks}
        for q in queries:
            if q in matched_answers:
                continue
            # 没有精确同名答案——不一定是 bug（比如笔记顺带引用了词典型），
            # 打印出来人工判断，附带这句实际挖出的所有答案方便对照。
            flagged.append((card_id, q, [a for _s, _e, a in blanks]))

    print(f"{args.html_path}: {len(cards)} 张卡片，{total_queries} 个语法点引用，"
          f"{total_blanked} 个实际挖空")
    if not flagged:
        print("OK: 每个语法点引用都能在实际挖空里找到完全匹配的答案")
        return
    print(f"\n{len(flagged)} 个语法点引用没有精确匹配的挖空答案（不一定是 bug，"
          f"人工过一遍确认）：")
    for card_id, q, answers in flagged:
        print(f"  {card_id}: 笔记引用「{q}」，这句实际挖出的答案={answers!r}")


if __name__ == "__main__":
    main()
