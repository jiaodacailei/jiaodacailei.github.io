# -*- coding: utf-8 -*-
"""
用法：
  python migrate_to_data_driven.py docs/private/<slug>/index.html

把一个已经用旧方式生成（内容直接烘焙进 index.html）的听力页，就地迁移成
data-driven 格式：从现有 index.html 里反向抽取内容（标题/副标题/侧栏标签/
密码哈希/每个 tab 的 mondai+question 分组/每句的 token化原文+翻译+笔记+
填空+说话人/単語テスト 的 quiz 数据），生成同目录下的 data.js（pretty-print），
再把 index.html 换成引用这份数据的精简 shell（跟 build_page.py --data-driven
生成的结构一致）。

**适用场景**：原始 enriched.json 已经不在了（比如清理过 tools/listening/work/
工作目录），没法重新跑一遍完整的 build_page.py --data-driven 流程，只能从
"已经生成好、当前正确"的 HTML 反向抽取——这跟 verify_blank_answers.py /
backfill_quiz_category.py 这些脚本是同一种处境（源数据没了，只能对着已发布
产物做文章）。**如果原始 enriched.json 还在，应该直接对着它重新跑
`build_page.py ... --data-driven`，不要用这个脚本**（反向抽取只能拿到当前
HTML 里已经烘焙进去的信息，比如 char_times 只能从 data-t 属性反推、精度
受限于当时保留的两位小数，不如从源头重新生成精确）。

抽取的 token 解析逻辑必须跟 build_page.py 的 ruby_html_from_tokens() 输出
格式一一对应（读那边的实现能看出这边在抽取什么结构）：每个 token 要么是
`<span class="tw" data-t="X.XX">INNER</span>`（INNER 是 `<ruby>ORIG<rt>KANA
</rt></ruby>` 或纯文本），要么是没有 data-t 包裹的裸 `<ruby>...</ruby>`
（没有 char_times 关联到这个 token 时），要么是裸文本（标点、或者
_split_kana_segments 拆出来的送假名部分）。

原地覆盖 index.html——运行前建议确认 git 工作区干净（这个脚本改的文件后续
可以用 git diff 复核，改坏了能直接 git checkout 撤销）。
"""
import sys
import re
import json
import html as html_mod
import argparse

sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0])
import build_page as bp

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SECTION_RE = re.compile(
    r'<section class="mondai-section[^"]*" id="m-(\d+)" data-scope="mondai">(.*?)</section>', re.S
)
_H2_RE = re.compile(r"<h2>(.*?)</h2>", re.S)
_QBLOCK_RE = re.compile(
    r'<div class="question-block" id="q-\d+-\d+" data-scope="question">(.*?)</div>\s*(?=<div class="question-block"|\Z)',
    re.S,
)
_H3_RE = re.compile(r"<h3>(.*?)</h3>", re.S)
_OVERVIEW_RE = re.compile(r'<p class="q-overview">(.*?)</p>', re.S)
_ANSWER_RE = re.compile(r'<details class="seg-answer">.*?<div>(.*?)</div>\s*</details>', re.S)
# <audio> 出现在卡片自己的正文最后、卡片自己的 </div> 之前（不是之后）——
# 见 build_page.py 的 sentence_card_html() 模板：
#   <div class="seg-card" id="card-aN">
#     ...speaker/seg-ja/seg-zh/seg-notes...
#     <audio ...></audio>
#   </div>
# 用 <audio> 标签本身当结束锚点（它在模板里位置固定、不会跟 seg-speaker/
# seg-notes 这些"卡片内部也有的 </div>"混淆），group4 是 audio 标签之前的
# 卡片正文，group5 直接是音频文件相对路径（不用再从 card_id 反推）。
_CARD_RE = re.compile(
    r'<div class="(seg-card[^"]*)" id="(card-a\d+)"(?:\s+data-blanks="([^"]*)")?>'
    r'(.*?)'
    r'<audio id="a\d+" preload="none" src="([^"]+)"></audio>\s*</div>',
    re.S,
)
_SPEAKER_RE = re.compile(r'<div class="seg-speaker">(.*?)</div>', re.S)
_SEG_JA_RE = re.compile(r'<p class="seg-ja">(.*?)</p>', re.S)
_SEG_ZH_RE = re.compile(r'<p class="seg-zh">(.*?)</p>', re.S)
_SEG_NOTES_RE = re.compile(r'<div class="seg-notes">(.*?)</div>', re.S)
_RUBY_RE = re.compile(r"^<ruby>(.*?)<rt>(.*?)</rt></ruby>$", re.S)
_PIECE_RE = re.compile(
    r'<span class="tw" data-t="([\d.]+)">(.*?)</span>'
    r'|(<ruby>.*?</ruby>)'
    r'|(<br\s*/?>)'
    r'|([^<]+)',
    re.S,
)
_TAG_RE = re.compile(r"<[^>]+>")


def unesc(s):
    return html_mod.unescape(s or "")


def parse_inner(inner_html):
    """<ruby>ORIG<rt>KANA</rt></ruby> 或纯文本 → (text, kana或None)。"""
    m = _RUBY_RE.match(inner_html)
    if m:
        return unesc(m.group(1)), unesc(m.group(2))
    return unesc(inner_html), None


def parse_tokens(seg_ja_html):
    tokens = []
    for m in _PIECE_RE.finditer(seg_ja_html):
        span_t, span_inner, bare_ruby, br, bare_text = m.groups()
        if span_t is not None:
            text, kana = parse_inner(span_inner)
            tok = {"text": text}
            if kana and kana != text:
                tok["kana"] = kana
            tok["t"] = round(float(span_t), 2)
            tokens.append(tok)
        elif bare_ruby is not None:
            text, kana = parse_inner(bare_ruby)
            tok = {"text": text}
            if kana and kana != text:
                tok["kana"] = kana
            tokens.append(tok)
        elif br is not None:
            tokens.append({"text": "\n"})
        else:
            text = unesc(bare_text)
            if text:
                tokens.append({"text": text})
    return tokens


def parse_card(card_class, card_id, blanks_attr, card_body, audio_src):
    speaker_m = _SPEAKER_RE.search(card_body)
    speaker = speaker_kana = None
    if speaker_m:
        text, kana = parse_inner(speaker_m.group(1).strip())
        speaker, speaker_kana = text, kana

    seg_ja_html = _SEG_JA_RE.search(card_body).group(1)
    tokens = parse_tokens(seg_ja_html)
    zh = unesc(_TAG_RE.sub("", _SEG_ZH_RE.search(card_body).group(1))).replace("<br>", "\n")
    notes_m = _SEG_NOTES_RE.search(card_body)
    notes = unesc(notes_m.group(1)) if notes_m else ""
    numeric_id = int(card_id.replace("card-a", ""))
    blanks = json.loads(unesc(blanks_attr)) if blanks_attr else []
    return {
        "id": numeric_id,
        "speaker": speaker,
        "speakerKana": speaker_kana,
        "tokens": tokens,
        "zh": zh,
        "notes": notes,
        "blanks": blanks,
        "audio": audio_src,
    }


def parse_mondai(mondai_label, body):
    questions = []
    qblocks = list(_QBLOCK_RE.finditer(body))
    if not qblocks:
        # 没有 question-block 包裹（简单流程，sentences 直接挂在 mondai 下）——
        # 这个 skill 目前的产出物都走 question-block 结构，理论上不会走到这条，
        # 保留只是不让脚本在意外结构上崩溃。
        return questions
    for qm in qblocks:
        qbody = qm.group(1)
        h3 = _H3_RE.search(qbody)
        label = unesc(h3.group(1)) if h3 else ""
        overview_m = _OVERVIEW_RE.search(qbody)
        overview = unesc(overview_m.group(1)) if overview_m else ""
        answer_m = _ANSWER_RE.search(qbody)
        answer = unesc(answer_m.group(1)) if answer_m else ""
        sentences = []
        for cm in _CARD_RE.finditer(qbody):
            card_class, card_id, blanks_attr, card_body, audio_src = cm.groups()
            sentences.append(parse_card(card_class, card_id, blanks_attr, card_body, unesc(audio_src)))
        questions.append({
            "question": label if label != mondai_label else "",
            "overview": overview,
            "answer": answer,
            "sentences": sentences,
        })
    return questions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html_path")
    args = ap.parse_args()

    html = open(args.html_path, encoding="utf-8").read()

    title_m = re.search(r"<h1>(.*?)</h1>", html, re.S)
    subtitle_m = re.search(r'<p class="post-page-meta">(.*?)</p>', html, re.S)
    side_nav_label_m = re.search(r'<div class="toc-label">(.*?)</div>', html, re.S)
    pwd_hash_m = re.search(r'data-hash="([^"]+)"', html)
    title = unesc(title_m.group(1)) if title_m else ""
    subtitle = unesc(subtitle_m.group(1)) if subtitle_m else ""
    side_nav_label = unesc(side_nav_label_m.group(1)) if side_nav_label_m else ""
    pwd_hash = pwd_hash_m.group(1) if pwd_hash_m else ""

    tabs = []
    quiz_data = None
    for sec_m in _SECTION_RE.finditer(html):
        body = sec_m.group(2)
        h2 = _H2_RE.search(body)
        label = unesc(h2.group(1)) if h2 else ""
        quiz_script_m = re.search(r'<script type="application/json" id="vocab-quiz-data">(.*?)</script>', body, re.S)
        if quiz_script_m:
            quiz_data = json.loads(quiz_script_m.group(1))
            continue
        questions = parse_mondai(label, body)
        tabs.append({"mondai": label, "questions": questions})

    lesson_data = {
        "title": title,
        "subtitle": subtitle,
        "sideNavLabel": side_nav_label,
        "tabs": tabs,
    }
    if quiz_data is not None:
        lesson_data["quiz"] = quiz_data

    out_dir = args.html_path.rsplit("/", 1)[0] if "/" in args.html_path else args.html_path.rsplit("\\", 1)[0]
    out_data_js = out_dir + "/data.js"
    with open(out_data_js, "w", encoding="utf-8") as f:
        f.write("window.LESSON_DATA = ")
        json.dump(lesson_data, f, ensure_ascii=False, indent=2)
        f.write(";\n")

    toc_label_html = f'<div class="toc-label">{html_mod.escape(side_nav_label)}</div>' if side_nav_label else ""
    shell = bp.SHELL_TEMPLATE.format(
        title=html_mod.escape(title),
        subtitle=subtitle,
        toc_label_html=toc_label_html,
        side_nav_label=html_mod.escape(side_nav_label),
        pwd_hash=pwd_hash,
        ICON_PAUSE=bp.ICON_PAUSE,
        ICON_GEAR=bp.ICON_GEAR,
        ICON_LOOP=bp.ICON_LOOP,
        ICON_CLOSE=bp.ICON_CLOSE,
        ICON_PREV=bp.ICON_PREV,
        ICON_NEXT=bp.ICON_NEXT,
        ICON_FIRST=bp.ICON_FIRST,
        ICON_LAST=bp.ICON_LAST,
    )
    with open(args.html_path, "w", encoding="utf-8") as f:
        f.write(shell)

    n_sentences = sum(len(q["sentences"]) for t in tabs for q in t["questions"])
    print(f"OK: {len(tabs)} 个 tab，{n_sentences} 句，quiz={'有' if quiz_data else '无'}")
    print(f"wrote {out_data_js}")
    print(f"rewrote {args.html_path} as shell")


if __name__ == "__main__":
    main()
