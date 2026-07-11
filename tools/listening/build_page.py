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
"""
import os
import json
import html
import hashlib
import argparse
import subprocess
import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


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
    return f'''
        <div class="seg-card" id="card-a{s['id']}">
          <p class="seg-ja">{s['furigana']}</p>
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


PAGE_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="robots" content="noindex, nofollow" />
<title>{title}</title>
<style>
  /* 本页不依赖外部的 /css/style.css——这是独立工具页，不是博客文章，
     直接把用到的 .toc / .toc-float / .post-page / .post-body 样式抄一份进来，
     保证本地 file:// 打开和线上部署视觉一致，不用等外部样式表加载。 */
  :root {{
    --navy: #0c1445; --blue: #2563eb; --blue-dark: #1d4ed8;
    --blue-light: #dbeafe; --blue-xlight: #eff6ff;
    --text: #0f172a; --text-muted: #64748b;
    --bg: #ffffff; --bg-soft: #f8fafc;
    --border: #e2e8f0; --radius: 10px;
    --shadow-xs: 0 1px 2px rgba(0,0,0,0.05);
    --shadow: 0 4px 20px rgba(0,0,0,0.09), 0 1px 4px rgba(0,0,0,0.05);
    --shadow-lg: 0 12px 40px rgba(0,0,0,0.12), 0 4px 12px rgba(0,0,0,0.06);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg-soft); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
  }}

  /* ── 复刻自 style.css：.post-page / .post-body ── */
  .post-page {{ max-width: 720px; margin: 0 auto; padding: 56px 32px 96px; }}
  .post-page-header {{ margin-bottom: 52px; padding-bottom: 36px; border-bottom: 1px solid var(--border); }}
  .post-page-header h1 {{
    font-size: clamp(24px, 4vw, 38px); font-weight: 900; line-height: 1.2;
    letter-spacing: -0.025em; margin-bottom: 20px; color: var(--text);
  }}
  .post-page-meta {{ display: flex; gap: 12px; flex-wrap: wrap; align-items: center; font-size: 14px; color: var(--text-muted); }}
  .post-body {{ line-height: 1.85; color: var(--text); font-size: 16px; }}
  .post-body h2, .post-body h3 {{
    cursor: pointer; transition: color .15s;
  }}
  .post-body h2:hover, .post-body h3:hover {{ color: var(--blue-dark); }}
  .post-body h2::after, .post-body h3::after {{
    content: "▶"; font-size: .55em; color: var(--text-muted); margin-left: 8px;
    opacity: 0; transition: opacity .15s;
  }}
  .post-body h2:hover::after, .post-body h3:hover::after {{ opacity: .7; }}
  .post-body h2 {{ font-size: 22px; font-weight: 800; margin: 32px 0 12px; letter-spacing: -0.02em; color: var(--text); }}
  .post-body h3 {{ font-size: 18px; font-weight: 700; margin: 22px 0 8px; }}

  /* ── 复刻自 style.css：.toc 桌面右侧栏 ── */
  .toc {{
    position: fixed; right: 32px; top: 88px; width: 210px;
    max-height: calc(100vh - 120px); overflow-y: auto;
    background: #fff; border: 1px solid var(--border); border-radius: 12px;
    box-shadow: 0 2px 14px rgba(0,0,0,0.07); padding: 16px 14px 18px; z-index: 100;
    scrollbar-width: thin; scrollbar-color: #e2e8f0 transparent;
  }}
  .toc-label {{
    font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
    color: #94a3b8; margin-bottom: 10px; padding-left: 8px;
  }}
  .toc ul {{ list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 2px; }}
  .toc-h2 > a {{
    display: flex; align-items: baseline; gap: 0; font-size: 13px; line-height: 1.4;
    color: #64748b; text-decoration: none; padding: 5px 8px; border-radius: 6px;
    border-left: 2px solid transparent; transition: color 0.15s, background 0.15s, border-color 0.15s;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  .toc-h2 > a:hover {{ color: #6366f1; background: #f0f0ff; }}
  .toc-active > a {{ color: #6366f1 !important; background: #eef2ff; border-left-color: #6366f1; font-weight: 600; }}
  @media (max-width: 1199px) {{ .toc {{ display: none; }} .post-page {{ padding-right: 48px; }} }}

  /* ── 复刻自 style.css：.toc-float 手机悬浮目录 ── */
  .toc-float {{ position: fixed; top: 90px; right: 0; z-index: 200; }}
  .toc-float-nums {{
    display: flex; flex-direction: column; align-items: center; gap: 2px;
    background: rgba(255,255,255,0.96); border: 1px solid #e2e8f0; border-right: none;
    border-radius: 20px 0 0 20px; padding: 6px 4px; box-shadow: -2px 2px 12px rgba(0,0,0,0.10);
    backdrop-filter: blur(6px); max-height: calc(100vh - 130px); overflow-y: auto; scrollbar-width: none;
  }}
  .toc-float-nums::-webkit-scrollbar {{ display: none; }}
  .toc-float-toggle {{
    width: 28px; height: 28px; border: none; background: none; color: #94a3b8;
    font-size: 16px; cursor: pointer; border-radius: 50%; display: flex;
    align-items: center; justify-content: center; margin-bottom: 2px;
    font-family: inherit; transition: color 0.15s, background 0.15s;
  }}
  .toc-float-toggle:hover {{ color: #6366f1; background: #eef2ff; }}
  .toc-float-num {{
    width: 26px; height: 26px; border: none; background: none; font-size: 11px;
    font-weight: 700; color: #94a3b8; cursor: pointer; border-radius: 50%; display: flex;
    align-items: center; justify-content: center; padding: 0; font-family: inherit; transition: all 0.15s;
  }}
  .toc-float-num:hover {{ background: #eef2ff; color: #6366f1; }}
  .toc-float-num.active {{ background: #6366f1; color: #fff; }}
  .toc-float-panel {{
    display: none; background: #fff; border: 1px solid #e2e8f0; border-radius: 14px 0 0 14px;
    border-right: none; box-shadow: -4px 4px 28px rgba(0,0,0,0.13);
    min-width: 200px; max-width: calc(100vw - 40px); max-height: 65vh; overflow-y: auto;
  }}
  .toc-float.toc-open .toc-float-nums {{ display: none; }}
  .toc-float.toc-open .toc-float-panel {{ display: block; }}
  .toc-float-header {{
    display: flex; align-items: center; justify-content: space-between; padding: 12px 14px 10px;
    font-size: 11px; font-weight: 700; color: #94a3b8; letter-spacing: 0.08em;
    text-transform: uppercase; border-bottom: 1px solid #f1f5f9;
  }}
  .toc-float-close {{
    border: none; background: none; color: #94a3b8; font-size: 14px; cursor: pointer;
    padding: 0; line-height: 1; font-family: inherit; transition: color 0.15s;
  }}
  .toc-float-close:hover {{ color: #6366f1; }}
  .toc-float-panel ul {{ list-style: none; padding: 6px 8px 10px; margin: 0; }}
  .toc-float-panel .toc-h2 > a {{
    display: block; font-size: 13px; line-height: 1.4; color: #475569; text-decoration: none;
    padding: 7px 8px; border-radius: 6px; border-left: 2px solid transparent; cursor: pointer;
    transition: color 0.15s, background 0.15s, border-color 0.15s;
  }}
  .toc-float-panel .toc-h2 > a:hover {{ color: #6366f1; background: #f0f0ff; }}
  .toc-float-panel .toc-active > a {{ color: #6366f1; background: #eef2ff; border-left-color: #6366f1; font-weight: 600; }}

  .seg-card {{
    background: #fff; border: 1px solid var(--border); border-radius: var(--radius);
    padding: 10px 14px; margin-bottom: 8px; box-shadow: var(--shadow-xs);
    cursor: pointer; position: relative;
    transition: border-color .15s, box-shadow .15s, background .15s;
  }}
  .seg-card:hover {{ border-color: var(--blue-light); box-shadow: 0 2px 8px rgba(37,99,235,0.12); }}
  .seg-card::after {{
    content: "▶"; position: absolute; top: 10px; right: 12px;
    font-size: 11px; color: var(--blue); opacity: 0; transition: opacity .15s; pointer-events: none;
  }}
  .seg-card:hover::after {{ opacity: .6; }}
  .seg-card.playing {{
    border-color: var(--blue); box-shadow: 0 0 0 2px var(--blue-light); background: var(--blue-xlight);
  }}
  .seg-ja {{ font-size: 16px; line-height: 2.2; margin: 0 24px 4px 0; }}
  .seg-ja ruby rt {{ font-size: 10px; color: var(--text-muted); font-style: normal; }}
  .seg-zh {{ color: var(--text-muted); font-size: 13px; font-style: italic; margin: 0 0 4px; }}
  .seg-notes {{
    font-size: 12.5px; line-height: 1.65; color: var(--text);
    background: var(--blue-xlight); border-left: 3px solid var(--blue);
    border-radius: 0 6px 6px 0; padding: 6px 10px;
  }}
  .q-overview {{ color: var(--text-muted); font-size: 14px; margin: 2px 0 10px; }}
  .seg-answer {{ margin: 0 0 10px; font-size: 13px; }}
  .seg-answer summary {{ cursor: pointer; color: var(--blue-dark); font-weight: 600; user-select: none; }}
  .seg-answer div {{
    margin-top: 6px; padding: 8px 12px; background: #fff7ed;
    border-left: 3px solid #f59e0b; border-radius: 0 6px 6px 0; line-height: 1.6;
  }}
  audio {{ display: none; }}
  .mondai-section {{ display: none; margin-bottom: 8px; }}
  .mondai-section.tab-active {{ display: block; }}
  .question-block {{ margin: 16px 0 22px; scroll-margin-top: 108px; }}
  .question-block:not(:first-child) {{ border-top: 1px solid var(--border); padding-top: 16px; }}
  .post-body h2 {{ scroll-margin-top: 108px; }}

  /* 显示模式：日文 / 中日文（默认）/ 中文 */
  /* 「日文」模式＝纯听力模式，中文相关的内容（翻译/概览/答案解析/笔记）都藏起来 */
  body.lang-ja-only .seg-zh,
  body.lang-ja-only .q-overview,
  body.lang-ja-only .seg-answer,
  body.lang-ja-only .seg-notes {{ display: none; }}
  body.lang-zh-only .seg-ja {{ display: none; }}

  /* ── 吸顶 tab 栏：問題1~5，点击切换，只显示当前大题 ── */
  .sticky-header {{
    position: fixed; top: 0; left: 0; right: 0; z-index: 300;
    background: rgba(255,255,255,0.96); backdrop-filter: blur(6px);
    border-bottom: 1px solid var(--border); box-shadow: 0 2px 10px rgba(0,0,0,0.04);
    display: flex; align-items: center; gap: 16px;
    padding: 10px 20px; flex-wrap: wrap;
  }}
  .sticky-header .sh-title {{
    font-size: 14px; font-weight: 700; color: var(--text);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px;
  }}
  .sticky-header .tab-bar {{ display: flex; gap: 6px; flex-wrap: wrap; }}
  .tab-btn {{
    border: 1px solid var(--border); background: var(--bg-soft); color: var(--text-muted);
    border-radius: 999px; padding: 4px 14px; font-size: 12px; font-weight: 600;
    cursor: pointer; transition: all .15s; white-space: nowrap;
  }}
  .tab-btn:hover {{ background: var(--blue-xlight); border-color: var(--blue-light); color: var(--blue-dark); }}
  .tab-btn.active {{ background: var(--blue); border-color: var(--blue); color: #fff; }}

  /* ── 小题导航：复用博客 toc.js 同款样式（.toc 桌面右侧栏 / .toc-float 手机悬浮），
     只是内容改成"当前 tab 的小题列表"，随 tab 切换动态换一批 ── */
  .toc {{ top: 110px; max-height: calc(100vh - 140px); }}
  .toc-float {{ top: 104px; }}
  @media (min-width: 1200px) {{ .toc-float {{ display: none; }} }}

  .side-nav-list {{ display: none; }}
  .side-nav-list.tab-active {{ display: flex; flex-direction: column; gap: 2px; }}
  /* .toc ul {{ display:flex }}（上面复刻的博客规则）比 .side-nav-list 选择器更具体，
     会覆盖掉隐藏效果，这里用更具体的选择器把优先级抢回来 */
  .toc ul.side-nav-list {{ display: none; }}
  .toc ul.side-nav-list.tab-active {{ display: flex; flex-direction: column; gap: 2px; }}
  .snm-nums-list {{ display: none; }}
  .snm-nums-list.tab-active {{ display: flex; flex-direction: column; gap: 2px; }}

  .post-page {{ padding-top: 110px; }}

  /* ── 右下角悬浮设置：播放速度 + 显示模式 ── */
  .settings-toggle {{
    position: fixed; right: 24px; bottom: 24px; z-index: 260;
    width: 48px; height: 48px; border-radius: 50%; border: none;
    background: var(--blue); color: #fff; font-size: 20px; cursor: pointer;
    box-shadow: 0 6px 20px rgba(37,99,235,0.35); transition: transform .15s;
  }}
  .settings-toggle:hover {{ transform: scale(1.06); }}
  .settings-panel {{
    display: none; position: fixed; right: 24px; bottom: 82px; z-index: 260;
    width: 216px; background: #fff; border: 1px solid var(--border); border-radius: 14px;
    box-shadow: var(--shadow-lg); padding: 16px;
  }}
  .settings-panel.open {{ display: block; }}
  .settings-group {{ margin-bottom: 14px; }}
  .settings-group:last-child {{ margin-bottom: 0; }}
  .settings-label {{
    font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase;
    letter-spacing: .06em; margin-bottom: 8px;
  }}
  .settings-options {{ display: flex; gap: 6px; flex-wrap: wrap; }}
  .settings-opt {{
    border: 1px solid var(--border); background: var(--bg-soft); color: var(--text);
    border-radius: 999px; padding: 5px 12px; font-size: 12px; cursor: pointer; transition: all .15s;
  }}
  .settings-opt:hover {{ background: var(--blue-xlight); border-color: var(--blue-light); }}
  .settings-opt.active {{ background: var(--blue); border-color: var(--blue); color: #fff; }}

  /* ── 悬浮迷你播放器：播放中才出现，导航（最初/前/播放/次/最後）+ 循环/停止 ── */
  .mini-player {{
    display: none; align-items: center; gap: 5px;
    position: fixed; left: 24px; right: 84px; bottom: 24px; z-index: 270;
    max-width: 480px; background: #fff; border: 1px solid var(--border);
    border-radius: 999px; box-shadow: var(--shadow-lg); padding: 6px 8px 6px 6px;
  }}
  .mini-player.active {{ display: flex; }}
  .mp-btn {{
    flex-shrink: 0; width: 32px; height: 32px; border-radius: 50%; border: none;
    background: var(--blue-xlight); color: var(--blue-dark); font-size: 13px; cursor: pointer;
    display: flex; align-items: center; justify-content: center; transition: all .15s;
  }}
  .mp-btn:hover {{ background: var(--blue-light); }}
  .mp-btn[disabled] {{ opacity: .3; cursor: default; pointer-events: none; }}
  .mp-playpause {{ background: var(--blue); color: #fff; font-size: 15px; }}
  .mp-playpause:hover {{ background: var(--blue-dark); }}
  .mp-loop.active {{ background: var(--blue); color: #fff; }}
  .mp-info {{ flex: 1; min-width: 0; }}
  .mp-scope {{ font-size: 13px; font-weight: 700; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .mp-pos {{ font-size: 11px; color: var(--text-muted); }}
  @media (max-width: 480px) {{
    .mini-player {{ left: 8px; right: 8px; bottom: 78px; max-width: none; gap: 3px; padding: 5px 6px; }}
    .mp-btn {{ width: 27px; height: 27px; font-size: 11px; }}
    .mp-playpause {{ font-size: 13px; }}
  }}

  #gate {{
    position: fixed; inset: 0; background: var(--navy); display: flex;
    align-items: center; justify-content: center; z-index: 999; flex-direction: column;
  }}
  #gate .box {{
    background: #fff; border-radius: 14px; padding: 32px 28px; width: 300px;
    text-align: center; box-shadow: var(--shadow-lg);
  }}
  #gate h2 {{ font-size: 16px; margin: 0 0 16px; }}
  #gate input {{
    width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px;
    font-size: 14px; margin-bottom: 12px; box-sizing: border-box;
  }}
  #gate button {{
    width: 100%; padding: 10px; border: none; border-radius: 8px;
    background: var(--blue); color: #fff; font-size: 14px; cursor: pointer;
  }}
  #gate .err {{ color: #ef4444; font-size: 12px; margin-top: 8px; min-height: 16px; }}
  #content {{ display: none; }}
</style>
</head>
<body>

<div id="gate">
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
      <div class="toc-float-header"><span>小問</span><button class="toc-float-close" id="snmClose">✕</button></div>
      {side_nav_lists_mobile}
    </div>
  </div>

  <button class="settings-toggle" id="settingsToggle" title="再生設定">⚙</button>
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
    <button class="mp-btn mp-first" id="mpFirst" title="最初" disabled>«</button>
    <button class="mp-btn mp-prev" id="mpPrev" title="前へ" disabled>‹</button>
    <button class="mp-btn mp-playpause" id="mpPlayPause" title="再生/一時停止">⏸</button>
    <button class="mp-btn mp-next" id="mpNext" title="次へ" disabled>›</button>
    <button class="mp-btn mp-last" id="mpLast" title="最後" disabled>»</button>
    <div class="mp-info">
      <div class="mp-scope" id="mpScope">-</div>
      <div class="mp-pos" id="mpPos"></div>
    </div>
    <button class="mp-btn mp-loop" id="mpLoop" title="ループ">⟲</button>
    <button class="mp-btn mp-stop" id="mpStop" title="停止">✕</button>
  </div>

  <div class="post-page">
    <div class="post-page-header">
      <h1>{title}</h1>
      <p class="post-page-meta">{subtitle}</p>
    </div>
    <div class="post-body">
      {sections}
    </div>
  </div>
</div>

<script>
(function() {{
  var HASH = "{pwd_hash}";
  async function sha256(str) {{
    var buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(str));
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
  }}
  function afterUnlock() {{
    document.getElementById("gate").style.display = "none";
    document.getElementById("content").style.display = "block";
  }}
  async function tryUnlock(pwd) {{
    var h = await sha256(pwd);
    if (h === HASH) {{
      afterUnlock();
      sessionStorage.setItem("unlocked-" + location.pathname, "1");
    }} else {{
      document.getElementById("pwdErr").textContent = "パスワードが違います";
    }}
  }}
  if (sessionStorage.getItem("unlocked-" + location.pathname) === "1") {{
    afterUnlock();
  }}
  document.getElementById("pwdBtn").addEventListener("click", function() {{
    tryUnlock(document.getElementById("pwdInput").value);
  }});
  document.getElementById("pwdInput").addEventListener("keydown", function(e) {{
    if (e.key === "Enter") tryUnlock(this.value);
  }});
}})();

// ── 统一播放器：逐句 / 小题整体 / 大题整体都走同一套状态，
//    点标题/内容播放，配合右下角悬浮迷你播放器暂停/继续/上一个/下一个/最前/最后/循环/停止 ──
(function() {{
  // navType: "sentence" | "question" | "mondai"；navSiblings 是同级兄弟节点数组（用于上一个/
  // 下一个/最前/最后导航，导航不跨级——句子不跨小题、小题不跨大题、大题就是顶层）；
  // loop 不随 playScope 重置，是迷你播放器里的全局开关，切换播放目标时保持原状态。
  var player = {{
    audios: [], idx: 0, loop: false, active: false, finished: false, scopeLabel: "",
    navType: null, navSiblings: [], navIndex: -1
  }};

  var miniPlayer = document.getElementById("miniPlayer");
  var mpScope = document.getElementById("mpScope");
  var mpPos = document.getElementById("mpPos");
  var mpPlayPause = document.getElementById("mpPlayPause");
  var mpLoop = document.getElementById("mpLoop");
  var mpStop = document.getElementById("mpStop");
  var mpFirst = document.getElementById("mpFirst");
  var mpPrev = document.getElementById("mpPrev");
  var mpNext = document.getElementById("mpNext");
  var mpLast = document.getElementById("mpLast");

  // 当前正在播放的句子加高亮效果，并自动滚动到可视区域内，方便连播/跳转时跟着看
  function setPlayingCard(audio) {{
    document.querySelectorAll(".seg-card.playing").forEach(function(c) {{ c.classList.remove("playing"); }});
    if (audio) {{
      var card = audio.closest(".seg-card");
      if (card) {{
        card.classList.add("playing");
        card.scrollIntoView({{ behavior: "smooth", block: "center" }});
      }}
    }}
  }}

  function updateMiniPlayer() {{
    if (!player.active) {{
      miniPlayer.classList.remove("active");
      return;
    }}
    miniPlayer.classList.add("active");
    mpScope.textContent = player.scopeLabel;
    mpPos.textContent = player.audios.length > 1 ? (player.idx + 1) + " / " + player.audios.length : "";
    var current = player.audios[player.idx];
    mpPlayPause.textContent = current && !current.paused ? "⏸" : "▶";
    mpLoop.classList.toggle("active", player.loop);
    var hasNav = !!player.navType && player.navSiblings.length > 1;
    var atFirst = player.navIndex <= 0;
    var atLast = player.navIndex < 0 || player.navIndex >= player.navSiblings.length - 1;
    mpFirst.disabled = !hasNav || atFirst;
    mpPrev.disabled = !hasNav || atFirst;
    mpNext.disabled = !hasNav || atLast;
    mpLast.disabled = !hasNav || atLast;
  }}

  // 主动停止/关闭：彻底隐藏迷你播放器（✕按钮、切 Tab、播完后点了别处）
  function stopPlayer() {{
    player.audios.forEach(function(a) {{ a.onended = null; a.pause(); }});
    player.active = false;
    player.finished = false;
    player.audios = [];
    setPlayingCard(null);
    updateMiniPlayer();
  }}
  document.addEventListener("stopAllAudio", stopPlayer);

  // 自然播完（没开循环）：迷你播放器不消失，停在"播完"状态，等用户点别处/点✕才关掉
  function finishPlayer() {{
    player.idx = Math.max(0, player.audios.length - 1);
    player.finished = true;
    setPlayingCard(null);
    updateMiniPlayer();
  }}

  function playNext() {{
    if (!player.active) return;
    if (player.idx >= player.audios.length) {{
      if (player.loop) {{ player.idx = 0; }} else {{ finishPlayer(); return; }}
    }}
    var a = player.audios[player.idx];
    a.currentTime = 0;
    a.onended = function() {{ player.idx++; playNext(); }};
    a.play();
    setPlayingCard(a);
    updateMiniPlayer();
  }}

  // 点句卡片/h3/h2 或迷你播放器导航按钮都走这一个入口。
  // navSiblings/navIndex 定位"这是同级里的第几个"，用于上一个/下一个/最前/最后。
  function playScope(navType, navSiblings, navIndex) {{
    var el = navSiblings[navIndex];
    if (navType === "mondai" && document.querySelectorAll(".tab-btn").length) {{
      // 切到别的大题要先把 Tab 切过去（会顺带停止当前播放），Tab 切换是同步的，
      // 切完再紧接着开始新播放，不会产生"播了一半又被 Tab 停掉"的竞态。
      document.dispatchEvent(new CustomEvent("activateTab", {{ detail: {{ idx: navIndex }} }}));
    }}
    var audios, label;
    if (navType === "sentence") {{
      audios = [el.querySelector("audio")];
      label = "文 " + (navIndex + 1) + " / " + navSiblings.length;
    }} else if (navType === "question") {{
      audios = Array.from(el.querySelectorAll("audio"));
      label = "小問 " + el.querySelector("h3").textContent.trim();
    }} else {{
      audios = Array.from(el.querySelectorAll("audio"));
      label = "大問 " + el.querySelector("h2").textContent.trim();
    }}
    player.audios.forEach(function(a) {{ a.onended = null; a.pause(); }});
    player.audios = audios;
    player.idx = 0;
    player.finished = false;
    player.scopeLabel = label;
    player.navType = navType;
    player.navSiblings = navSiblings;
    player.navIndex = navIndex;
    player.active = true;
    playNext();
  }}

  mpPlayPause.addEventListener("click", function() {{
    if (!player.active) return;
    if (player.finished) {{
      player.finished = false;
      player.idx = 0;
      playNext();
      return;
    }}
    var current = player.audios[player.idx];
    if (!current) return;
    if (current.paused) {{ current.play(); }} else {{ current.pause(); }}
    updateMiniPlayer();
  }});
  // 播完后停在原地，点了迷你播放器以外的任何地方才把它关掉
  document.addEventListener("click", function(e) {{
    if (player.finished && player.active && !miniPlayer.contains(e.target)) {{
      stopPlayer();
    }}
  }});
  mpLoop.addEventListener("click", function() {{
    if (!player.active) return;
    player.loop = !player.loop;
    updateMiniPlayer();
  }});
  mpStop.addEventListener("click", stopPlayer);
  mpFirst.addEventListener("click", function() {{
    if (player.navType) playScope(player.navType, player.navSiblings, 0);
  }});
  mpLast.addEventListener("click", function() {{
    if (player.navType) playScope(player.navType, player.navSiblings, player.navSiblings.length - 1);
  }});
  mpPrev.addEventListener("click", function() {{
    if (player.navType && player.navIndex > 0) playScope(player.navType, player.navSiblings, player.navIndex - 1);
  }});
  mpNext.addEventListener("click", function() {{
    if (player.navType && player.navIndex < player.navSiblings.length - 1) {{
      playScope(player.navType, player.navSiblings, player.navIndex + 1);
    }}
  }});

  document.querySelectorAll(".seg-card").forEach(function(card) {{
    card.addEventListener("click", function() {{
      var block = card.closest(".question-block");
      var siblings = block ? Array.from(block.querySelectorAll(".seg-card")) : [card];
      playScope("sentence", siblings, siblings.indexOf(card));
    }});
  }});

  document.querySelectorAll('.question-block[data-scope="question"]').forEach(function(block) {{
    var h3 = block.querySelector("h3");
    h3.addEventListener("click", function() {{
      var mondaiSec = block.closest(".mondai-section");
      var siblings = mondaiSec ? Array.from(mondaiSec.querySelectorAll('.question-block[data-scope="question"]')) : [block];
      playScope("question", siblings, siblings.indexOf(block));
    }});
  }});

  document.querySelectorAll('.mondai-section[data-scope="mondai"]').forEach(function(section) {{
    var h2 = section.querySelector("h2");
    h2.addEventListener("click", function() {{
      var siblings = Array.from(document.querySelectorAll('.mondai-section[data-scope="mondai"]'));
      playScope("mondai", siblings, siblings.indexOf(section));
    }});
  }});
}})();

// ── Tab 切换：問題1~5，点击后只显示该大题内容 + 对应的小题导航 ──
(function() {{
  var tabBtns = Array.from(document.querySelectorAll(".tab-btn"));
  if (!tabBtns.length) return;

  // 直接标记某小题为当前高亮，不读取任何布局属性（避免强制回流）
  function setCurrent(targetId) {{
    document.querySelectorAll(".side-nav-btn").forEach(function(b) {{
      var isCurrent = b.dataset.target === targetId;
      if (b.tagName === "A") {{
        b.parentElement.classList.toggle("toc-active", isCurrent);
      }} else {{
        b.classList.toggle("active", isCurrent);
      }}
    }});
  }}

  function activate(idx, opts) {{
    opts = opts || {{}};
    document.dispatchEvent(new CustomEvent("stopAllAudio"));

    tabBtns.forEach(function(b, i) {{ b.classList.toggle("active", i === idx); }});
    document.querySelectorAll('.mondai-section[data-scope="mondai"]').forEach(function(sec, i) {{
      sec.classList.toggle("tab-active", i === idx);
    }});
    document.querySelectorAll(".side-nav-list").forEach(function(list, i) {{
      list.classList.toggle("tab-active", i === idx);
    }});
    document.querySelectorAll(".snm-nums-list").forEach(function(list, i) {{
      list.classList.toggle("tab-active", i === idx);
    }});
    // 切换后总是回到顶部，所以新 tab 的第一小题必然是"当前项"，直接设置，不用等滚动测量
    setCurrent("q-" + (idx + 1) + "-1");
    if (!opts.skipScroll) window.scrollTo({{ top: 0, behavior: "smooth" }});
  }}

  tabBtns.forEach(function(b, i) {{
    b.addEventListener("click", function() {{ activate(i); }});
  }});
  // 迷你播放器导航到别的大题时触发，跳过"滚回顶部"（接下来会直接滚到正在播放的那句）
  document.addEventListener("activateTab", function(e) {{
    activate(e.detail.idx, {{ skipScroll: true }});
  }});
  activate(0, {{ skipScroll: true }});

  // 小题导航（复用博客 .toc / .toc-float 同款结构）：点击滚动到对应 question-block
  var sideNavMobile = document.getElementById("sideNavMobile");
  document.querySelectorAll(".side-nav-btn").forEach(function(b) {{
    b.addEventListener("click", function(e) {{
      e.preventDefault();
      var target = document.getElementById(b.dataset.target);
      if (target) window.scrollTo({{ top: target.offsetTop - 100, behavior: "smooth" }});
      if (sideNavMobile) sideNavMobile.classList.remove("toc-open");
    }});
  }});

  // 高亮当前小题（滚动时用）：用 requestAnimationFrame 节流，避免每个 scroll 事件都同步读布局触发强制回流
  function highlightCurrentQuestion() {{
    var activeSection = document.querySelector(".mondai-section.tab-active");
    if (!activeSection) return;
    var blocks = Array.from(activeSection.querySelectorAll(".question-block"));
    var y = window.scrollY + 130, cur = null;
    blocks.forEach(function(bl) {{ if (bl.offsetTop <= y) cur = bl.id; }});
    if (cur) setCurrent(cur);
  }}
  var rafPending = false;
  function scheduleHighlight() {{
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(function() {{ rafPending = false; highlightCurrentQuestion(); }});
  }}
  window.addEventListener("scroll", scheduleHighlight, {{ passive: true }});

  var snmToggle = document.getElementById("snmToggle");
  var snmClose = document.getElementById("snmClose");
  if (snmToggle) snmToggle.addEventListener("click", function() {{ sideNavMobile.classList.add("toc-open"); }});
  if (snmClose) snmClose.addEventListener("click", function() {{ sideNavMobile.classList.remove("toc-open"); }});
}})();

// ── 右下角悬浮设置：播放速度 + 显示模式（存 localStorage，刷新/换 tab 都记得住）──
(function() {{
  var SPEED_KEY = "n2listen-speed", LANG_KEY = "n2listen-lang";
  var speed = parseFloat(localStorage.getItem(SPEED_KEY) || "1");
  var lang = localStorage.getItem(LANG_KEY) || "both";

  function applySpeed() {{
    document.querySelectorAll("audio").forEach(function(a) {{ a.playbackRate = speed; }});
  }}
  function applyLang() {{
    document.body.classList.remove("lang-ja-only", "lang-zh-only");
    if (lang === "ja") document.body.classList.add("lang-ja-only");
    if (lang === "zh") document.body.classList.add("lang-zh-only");
  }}
  applySpeed();
  applyLang();

  document.querySelectorAll("#speedOptions .settings-opt").forEach(function(b) {{
    b.classList.toggle("active", parseFloat(b.dataset.speed) === speed);
    b.addEventListener("click", function() {{
      speed = parseFloat(b.dataset.speed);
      localStorage.setItem(SPEED_KEY, speed);
      document.querySelectorAll("#speedOptions .settings-opt").forEach(function(x) {{ x.classList.toggle("active", x === b); }});
      applySpeed();
    }});
  }});
  document.querySelectorAll("#langOptions .settings-opt").forEach(function(b) {{
    b.classList.toggle("active", b.dataset.lang === lang);
    b.addEventListener("click", function() {{
      lang = b.dataset.lang;
      localStorage.setItem(LANG_KEY, lang);
      document.querySelectorAll("#langOptions .settings-opt").forEach(function(x) {{ x.classList.toggle("active", x === b); }});
      applyLang();
    }});
  }});

  var settingsToggle = document.getElementById("settingsToggle");
  var settingsPanel = document.getElementById("settingsPanel");
  settingsToggle.addEventListener("click", function(e) {{
    e.stopPropagation();
    settingsPanel.classList.toggle("open");
  }});
  document.addEventListener("click", function(e) {{
    if (settingsPanel.classList.contains("open") && !settingsPanel.contains(e.target) && e.target !== settingsToggle) {{
      settingsPanel.classList.remove("open");
    }}
  }});
}})();
</script>

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
    )

    out_html = os.path.join(args.out_dir, "index.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"Wrote {out_html} and {len(sentences)} audio clips to {audio_out_dir}")


if __name__ == "__main__":
    main()
