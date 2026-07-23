# -*- coding: utf-8 -*-
"""
用法：
  python build_page.py <原始音频> <enriched.json> <输出目录> \
      --title "标题" --subtitle "副标题" --password sairai

<enriched.json> 是 merge_groups.py 的输出：{"sentences": [...], "questions": [...]}
（简单流程/无分组内容也可以用，questions 传空数组即可，此时不生成 h3/概览/答案，
 只有 h2=mondai 或完全没有分组，直接把所有 sentences 按 h2 分组渲染）。

<输出目录> 会生成：
  index.html        密码门 + noindex + 博客同款目录侧栏 + 三层播放控制的听力页
  audio/seg-NN.mp3   每句切出来的音频片段

生成后把 <输出目录> 放到 docs/private/<slug>/ 下即可通过个人网站访问，
但不要把它加进 blog/index.html、posts.json 或站内导航——保持"不公开链接"。

页面依赖三个共用文件（不再是每个页面各自内联一份，改样式/改交互只用改这些文件
一次，不用重新生成每个页面）：docs/css/listening-page.css、docs/js/listening-page.js
（听力页专属：播放器/tab/跟读高亮），docs/js/private-gate.js（密码门逻辑，不只是
听力页在用，其它私有页面比如枢纽页也用这份——解锁状态按密码哈希存 sessionStorage，
不按页面路径存，同一个密码在多个页面通用时解锁一处、其它页面自动跳过登录）。
**本地验证不能再直接双击 index.html 用 file:// 打开**——浏览器对 file:// 页面加载
本地其它文件有安全限制，绝对路径 `/css/...`、`/js/...` 解析不到。改用
`python -m http.server` 在 docs/ 目录起个本地服务器，用 http://localhost:8000/
private/<slug>/ 访问。
"""
import os
import json
import html
import hashlib
import argparse
import subprocess
import imageio_ffmpeg
import pykakasi

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
_kks = pykakasi.kakasi()


def _is_kanji(ch):
    return '一' <= ch <= '鿿'


# pykakasi 是按单字/常见复合词猜读音的，罕见组合容易读错，已经踩过两类坑：
# 1) 单字在孤立语境下的默认读音，放进特定复合词里其实要变——"表"单独最常见的
#    读音是おもて（"正面"），但在"スケジュール表"（日程表）这个复合词里应该读
#    ひょう；这类只在"上一个 token 是特定词"时才生效，不能无条件覆盖每一个
#    "表"字（其它页面/其它上下文里独立出现的"表"多半确实该读おもて）。
# 2) 纯粹的库内部转换 bug，不管上下文都会错——"入っ"（"入る"促音变前的词干，
#    后面接 て/たり/た）pykakasi 会输出无效假名"いっっ"（多出一个っ），这个
#    token 只可能来自五段动词"入る"，不存在"入っ"读别的音的情况，可以无条件覆盖。
# 两种覆盖都只改 `hira`（显示的读音文本），不改 `orig`，字符长度对
# char_times 下标的计算完全没有影响，不会连带影响跟读高亮的时间戳对齐。
_TOKEN_READING_OVERRIDES_BY_PREV = {
    ("スケジュール", "表"): "ひょう",
    # "その日"（那天，独立指某一天）该读ひ，pykakasi 默认给孤立的"日"字读にち
    # （日期计数用法，比如"1日"=いちにち这种搭配才对）。
    ("その", "日"): "ひ",
    # "20日"是日期特殊读法はつか（不是にじゅうにち），只在"20"后面才触发，不影响
    # "1日"(いちにち)/"3日"(みっか，还没遇到但同理不受影响)这些其它数字+日的组合。
    ("20", "日"): "はつか",
}
_TOKEN_READING_OVERRIDES_UNCONDITIONAL = {
    "入っ": "はいっ",
}


def ruby_html(text, char_times=None):
    """假名注音渲染。有 char_times（refine_boundaries.py 用词级时间戳文本对齐算出来
    的、这句里每个字符对应的绝对播放时间）时，额外给每个分词包一层
    `<span class="tw" data-t="...">`，播放时前端按 audio.currentTime 找到当前应该
    高亮的词。没有 char_times（简单流程没跑 refine_boundaries.py，或者这句对齐质量
    太差被跳过）就退化成纯 <ruby> 输出，不带高亮能力——静态展示效果不受影响，
    只是没有跟读高亮。
    """
    lines = text.split("\n")
    out_lines = []
    char_idx = 0
    for li, line in enumerate(lines):
        tokens = _kks.convert(line)
        parts = []
        prev_orig = None
        for t in tokens:
            orig = t['orig']
            hira = t['hira']
            if orig in _TOKEN_READING_OVERRIDES_UNCONDITIONAL:
                hira = _TOKEN_READING_OVERRIDES_UNCONDITIONAL[orig]
            elif (prev_orig, orig) in _TOKEN_READING_OVERRIDES_BY_PREV:
                hira = _TOKEN_READING_OVERRIDES_BY_PREV[(prev_orig, orig)]
            prev_orig = orig
            tok_len = len(orig)
            t_time = None
            if char_times is not None and char_idx < len(char_times):
                t_time = char_times[char_idx]
            char_idx += tok_len
            if any(_is_kanji(ch) for ch in orig) and hira != orig:
                inner = f'<ruby>{orig}<rt>{hira}</rt></ruby>'
            else:
                inner = orig
            # 标点/符号（「、」「。」「?」之类）不算"读到的词"，不参与跟读高亮——
            # pykakasi 分词里纯标点 token 没有假名/汉字，isalnum() 全假，用这个判断跳过。
            has_content = any(ch.isalnum() for ch in orig)
            if t_time is not None and has_content:
                parts.append(f'<span class="tw" data-t="{t_time:.2f}">{inner}</span>')
            else:
                parts.append(inner)
        out_lines.append(''.join(parts))
        if li < len(lines) - 1:
            char_idx += 1  # 换行符本身也占一个字符位，对齐 char_times 的下标
    return '<br>'.join(out_lines)


def cut_segments(audio_path, sentences, out_audio_dir):
    os.makedirs(out_audio_dir, exist_ok=True)
    for s in sentences:
        out_file = os.path.join(out_audio_dir, f"seg-{s['id']:03d}.mp3")
        if os.path.exists(out_file):
            continue
        dur = s["end"] - s["start"]
        subprocess.run(
            [FFMPEG, "-y", "-ss", str(s["start"]), "-t", str(dur), "-i", audio_path,
             "-ar", "44100", "-ac", "1", "-b:a", "96k", out_file],
            capture_output=True
        )


def sentence_card_html(s, audio_rel):
    zh = html.escape(s["zh"]).replace("\n", "<br>")
    notes_html = ""
    if s.get("notes"):
        notes_html = f'<div class="seg-notes">{html.escape(s["notes"])}</div>'
    # char_times 是绝对时间戳（跟 s["start"]/s["end"] 一个坐标系），但这句自己的
    # audio 文件是从它自己的 start 开始单独切出来的（文件内 t=0 对应 s["start"]），
    # 所以喂给 ruby_html 之前要减去 s["start"] 转成这个音频文件内部的相对时间。
    char_times = s.get("char_times")
    rel_char_times = [round(t - s["start"], 2) for t in char_times] if char_times else None
    ja_html = ruby_html(s["text"], rel_char_times) if rel_char_times else s["furigana"]
    return f'''
        <div class="seg-card" id="card-a{s['id']}">
          <p class="seg-ja">{ja_html}</p>
          <p class="seg-zh">{zh}</p>{notes_html}
          <audio id="a{s['id']}" preload="none" src="{audio_rel}seg-{s['id']:03d}.mp3"></audio>
        </div>'''


def question_block_html(mondai_idx, q_idx, question_label, overview, answer, sentences, audio_rel):
    overview_html = f'<p class="q-overview">{html.escape(overview)}</p>' if overview else ""
    answer_html = ""
    if answer:
        answer_html = f'''
        <details class="seg-answer">
          <summary>答えを見る</summary>
          <div>{html.escape(answer)}</div>
        </details>'''
    cards = "\n".join(sentence_card_html(s, audio_rel) for s in sentences)
    scope_id = f"q-{mondai_idx}-{q_idx}"
    return f'''
      <div class="question-block" id="{scope_id}" data-scope="question">
        <h3>{html.escape(question_label)}</h3>
        {overview_html}{answer_html}
        {cards}
      </div>'''


def mondai_section_html(mondai_idx, mondai_label, question_blocks_html, active):
    scope_id = f"m-{mondai_idx}"
    cls = "mondai-section tab-active" if active else "mondai-section"
    return f'''
    <section class="{cls}" id="{scope_id}" data-scope="mondai">
      <h2>{html.escape(mondai_label)}</h2>
      {question_blocks_html}
    </section>'''


def side_nav_list_html(mondai_idx, question_labels, active):
    """桌面 .toc 侧栏 / 手机 .toc-float-panel 都用这份列表（结构与 toc.js 生成的一致）。"""
    cls = "side-nav-list tab-active" if active else "side-nav-list"
    items = "\n".join(
        f'<li class="toc-h2"><a class="side-nav-btn" data-target="q-{mondai_idx}-{qi}">{html.escape(label)}</a></li>'
        for qi, label in enumerate(question_labels, 1)
    )
    return f'<ul class="{cls}" data-mondai-idx="{mondai_idx}">{items}</ul>'


def mobile_nums_list_html(mondai_idx, question_labels, active):
    """手机悬浮目录收起状态下的数字按钮条（.toc-float-nums 内）。"""
    cls = "snm-nums-list tab-active" if active else "snm-nums-list"
    btns = "\n".join(
        f'<button class="toc-float-num side-nav-btn" data-target="q-{mondai_idx}-{qi}">{qi}</button>'
        for qi in range(1, len(question_labels) + 1)
    )
    return f'<div class="{cls}" data-mondai-idx="{mondai_idx}">{btns}</div>'


# 播放/暂停/循环/设置/关闭这几个图标改用内联 SVG（fill="currentColor"）而不是 emoji 字符
# （▶⏸⚙⟲✕之类）——这些字符在部分移动端浏览器上会被系统符号字体接管渲染，忽略 CSS
# color（表现为图标发灰而不是预期的白色/蓝色）、且字形本身的可视重心跟按钮的 flex
# 居中假设对不上（表现为图标偏离圆心）。SVG 路径取自 Material Design 图标，跨平台
# 渲染结果完全一致，不存在字体兜底的不确定性。
# ICON_PLAY 不在这里定义——播放/暂停图标运行时动态切换（点按钮时用哪个取决于播放
# 状态），这个切换逻辑在共享的 listening-page.js 里，同一份 SVG 常量在那边重复定义
# 了一次，不从这里传过去（这里只放"生成时渲染一次就不再变"的静态图标）。
ICON_PAUSE = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>'
ICON_GEAR = ('<svg viewBox="0 0 24 24" fill="currentColor"><path d="M19.14,12.94c0.04-0.3,0.06-0.61,'
             '0.06-0.94c0-0.32-0.02-0.64-0.07-0.94l2.03-1.58c0.18-0.14,0.23-0.41,0.12-0.61l-1.92-3.32'
             'c-0.12-0.22-0.37-0.29-0.59-0.22l-2.39,0.96c-0.5-0.38-1.03-0.7-1.62-0.94L14.4,2.81c-0.04'
             '-0.24-0.24-0.41-0.48-0.41h-3.84c-0.24,0-0.43,0.17-0.47,0.41L9.25,5.35C8.66,5.59,8.12,5.92,'
             '7.63,6.29L5.24,5.33c-0.22-0.08-0.47,0-0.59,0.22L2.74,8.87C2.62,9.08,2.66,9.34,2.86,9.48'
             'l2.03,1.58C4.84,11.36,4.8,11.69,4.8,12s0.02,0.64,0.07,0.94l-2.03,1.58c-0.18,0.14,-0.23,'
             '0.41,-0.12,0.61l1.92,3.32c0.12,0.22,0.37,0.29,0.59,0.22l2.39-0.96c0.5,0.38,1.03,0.7,1.62,'
             '0.94l0.36,2.54c0.05,0.24,0.24,0.41,0.48,0.41h3.84c0.24,0,0.44-0.17,0.47-0.41l0.36-2.54'
             'c0.59-0.24,1.13-0.56,1.62-0.94l2.39,0.96c0.22,0.08,0.47,0,0.59-0.22l1.92-3.32c0.12-0.22,'
             '0.07-0.47-0.12-0.61L19.14,12.94z M12,15.6c-1.98,0-3.6-1.62-3.6-3.6s1.62-3.6,3.6-3.6s3.6,'
             '1.62,3.6,3.6S13.98,15.6,12,15.6z"/></svg>')
ICON_LOOP = ('<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10'
             'H7v-3l-4 4 4 4v-3h12v-6h-2v4z"/></svg>')
ICON_CLOSE = ('<svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 '
              '5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>')
# 上一个/下一个/最前/最后导航原来用 «‹›» 这几个字符，实测太细太淡，不容易注意到——
# 换成跟其它按钮一样的实心 SVG 箭头，视觉粗细一致，也更显眼。
ICON_PREV = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z"/></svg>'
ICON_NEXT = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>'
ICON_FIRST = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z"/></svg>'
ICON_LAST = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg>'

PAGE_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="robots" content="noindex, nofollow" />
<title>{title}</title>
<link rel="stylesheet" href="/css/listening-page.css">
</head>
<body>

<div id="gate" data-hash="{pwd_hash}">
  <div class="box">
    <h2>&#128274; パスワードを入力してください</h2>
    <input type="password" id="pwdInput" placeholder="パスワード" autofocus />
    <button id="pwdBtn">開く</button>
    <div class="err" id="pwdErr"></div>
  </div>
</div>

<div id="content">
  <div class="sticky-header">
    <div class="sh-title">{title}</div>
    <div class="tab-bar">{tab_buttons}</div>
  </div>

  <nav class="toc" id="sideNav">
    <div class="toc-label">小問</div>
    {side_nav_lists}
  </nav>

  <div class="toc-float" id="sideNavMobile">
    <div class="toc-float-nums">
      <button class="toc-float-toggle" id="snmToggle" title="目次を開く">≡</button>
      {mobile_nums_lists}
    </div>
    <div class="toc-float-panel">
      <div class="toc-float-header"><span>小問</span><button class="toc-float-close" id="snmClose">{ICON_CLOSE}</button></div>
      {side_nav_lists_mobile}
    </div>
  </div>

  <button class="settings-toggle" id="settingsToggle" title="再生設定">{ICON_GEAR}</button>
  <div class="settings-panel" id="settingsPanel">
    <div class="settings-group">
      <div class="settings-label">再生速度</div>
      <div class="settings-options" id="speedOptions">
        <button class="settings-opt" data-speed="0.5">0.5x</button>
        <button class="settings-opt" data-speed="0.75">0.75x</button>
        <button class="settings-opt active" data-speed="1">1x</button>
        <button class="settings-opt" data-speed="1.2">1.2x</button>
      </div>
    </div>
    <div class="settings-group">
      <div class="settings-label">表示</div>
      <div class="settings-options" id="langOptions">
        <button class="settings-opt" data-lang="ja">日本語</button>
        <button class="settings-opt active" data-lang="both">日中</button>
        <button class="settings-opt" data-lang="zh">中国語</button>
      </div>
    </div>
  </div>

  <div class="mini-player" id="miniPlayer">
    <button class="mp-btn mp-first" id="mpFirst" title="最初" disabled>{ICON_FIRST}</button>
    <button class="mp-btn mp-prev" id="mpPrev" title="前へ" disabled>{ICON_PREV}</button>
    <button class="mp-btn mp-playpause" id="mpPlayPause" title="再生/一時停止">{ICON_PAUSE}</button>
    <button class="mp-btn mp-next" id="mpNext" title="次へ" disabled>{ICON_NEXT}</button>
    <button class="mp-btn mp-last" id="mpLast" title="最後" disabled>{ICON_LAST}</button>
    <div class="mp-info">
      <div class="mp-scope" id="mpScope">-</div>
      <div class="mp-pos" id="mpPos"></div>
    </div>
    <button class="mp-btn mp-loop" id="mpLoop" title="ループ">{ICON_LOOP}</button>
    <button class="mp-btn mp-stop" id="mpStop" title="停止">{ICON_CLOSE}</button>
  </div>

  <div class="post-page">
    <div class="post-page-header">
      <h1>{title}</h1>
      <p class="post-page-meta">{subtitle}</p>
      <p class="play-hint">▶ 点击题目标题或句子卡片即可播放对应音频</p>
    </div>
    <div class="post-body">
      {sections}
    </div>
  </div>
</div>

<script src="/js/private-gate.js" defer></script>
<script src="/js/listening-page.js" defer></script>

</body>
</html>
'''


def build_sections_html(sentences, questions, audio_rel):
    # group sentences by (mondai, question) preserving first-seen order
    by_mondai = []
    mondai_index = {}
    for s in sentences:
        m = s.get("mondai") or "听力材料"
        if m not in mondai_index:
            mondai_index[m] = len(by_mondai)
            by_mondai.append({"mondai": m, "questions": [], "q_index": {}})
        mrec = by_mondai[mondai_index[m]]
        q = s.get("question") or ""
        if q not in mrec["q_index"]:
            mrec["q_index"][q] = len(mrec["questions"])
            mrec["questions"].append({"question": q, "sentences": []})
        mrec["questions"][mrec["q_index"][q]]["sentences"].append(s)

    overview_map = {(q["mondai"], q["question"]): q for q in questions}

    sections = []
    nav_lists = []       # 桌面 .toc 和手机 .toc-float-panel 共用（同一份 <ul> 标记）
    nav_nums_mobile = []  # 手机悬浮收起状态下的数字按钮条
    for mi, mrec in enumerate(by_mondai, 1):
        is_first = (mi == 1)
        q_blocks = []
        q_labels = []
        for qi, qrec in enumerate(mrec["questions"], 1):
            label = qrec["question"] or mrec["mondai"]
            q_labels.append(label)
            meta = overview_map.get((mrec["mondai"], qrec["question"]), {})
            q_blocks.append(question_block_html(
                mi, qi, label,
                meta.get("overview", ""), meta.get("answer", ""),
                qrec["sentences"], audio_rel
            ))
        sections.append(mondai_section_html(mi, mrec["mondai"], "\n".join(q_blocks), is_first))
        nav_lists.append(side_nav_list_html(mi, q_labels, is_first))
        nav_nums_mobile.append(mobile_nums_list_html(mi, q_labels, is_first))

    tab_buttons = "\n".join(
        f'<button class="tab-btn{" active" if mi == 1 else ""}" data-mondai-idx="{mi}">{html.escape(mrec["mondai"])}</button>'
        for mi, mrec in enumerate(by_mondai, 1)
    )
    return (
        "\n".join(sections), tab_buttons,
        "\n".join(nav_lists), "\n".join(nav_lists), "\n".join(nav_nums_mobile),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("enriched_json")
    ap.add_argument("out_dir")
    ap.add_argument("--title", required=True)
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--password", help="设置新密码（跟 --password-hash 二选一）")
    ap.add_argument("--password-hash", help="复用已有页面的密码哈希（跟 --password 二选一），"
                     "适合改完边界/文案重新生成页面但密码不用变的场景——不用把明文密码再传一遍")
    args = ap.parse_args()
    if not args.password and not args.password_hash:
        ap.error("must provide --password or --password-hash")
    if args.password and args.password_hash:
        ap.error("--password and --password-hash are mutually exclusive")

    with open(args.enriched_json, encoding="utf-8") as f:
        data = json.load(f)
    sentences = data["sentences"]
    questions = data.get("questions", [])

    os.makedirs(args.out_dir, exist_ok=True)
    audio_out_dir = os.path.join(args.out_dir, "audio")
    cut_segments(args.audio, sentences, audio_out_dir)

    sections, tab_buttons, side_nav_lists, side_nav_lists_mobile, mobile_nums_lists = \
        build_sections_html(sentences, questions, "audio/")
    pwd_hash = args.password_hash or hashlib.sha256(args.password.encode("utf-8")).hexdigest()

    page = PAGE_TEMPLATE.format(
        title=html.escape(args.title),
        subtitle=args.subtitle,
        sections=sections,
        tab_buttons=tab_buttons,
        side_nav_lists=side_nav_lists,
        side_nav_lists_mobile=side_nav_lists_mobile,
        mobile_nums_lists=mobile_nums_lists,
        pwd_hash=pwd_hash,
        ICON_PAUSE=ICON_PAUSE,
        ICON_GEAR=ICON_GEAR,
        ICON_LOOP=ICON_LOOP,
        ICON_CLOSE=ICON_CLOSE,
        ICON_PREV=ICON_PREV,
        ICON_NEXT=ICON_NEXT,
        ICON_FIRST=ICON_FIRST,
        ICON_LAST=ICON_LAST,
    )

    out_html = os.path.join(args.out_dir, "index.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"Wrote {out_html} and {len(sentences)} audio clips to {audio_out_dir}")


if __name__ == "__main__":
    main()
