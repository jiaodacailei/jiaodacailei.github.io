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
        <div class="seg-card">
          <div class="seg-head">
            <span class="seg-num">{s['id']:03d}</span>
            <div class="seg-controls">
              <button class="seg-btn play" data-target="a{s['id']}" title="播放/暂停">▶ 播放</button>
              <button class="seg-btn replay" data-target="a{s['id']}" title="从头重放">↺ 重放</button>
              <button class="seg-btn loop" data-target="a{s['id']}" title="单句循环">⟲ 循环</button>
            </div>
          </div>
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
          <summary>点击查看答案</summary>
          <div>{html.escape(answer)}</div>
        </details>'''
    cards = "\n".join(sentence_card_html(s, audio_rel) for s in sentences)
    scope_id = f"q-{mondai_idx}-{q_idx}"
    return f'''
      <div class="question-block" id="{scope_id}" data-scope="question">
        <h3>{html.escape(question_label)}
          <span class="scope-controls">
            <button class="scope-btn q-play" title="播放整题">▶ 播放整题</button>
            <button class="scope-btn q-loop" title="循环整题">⟲ 循环整题</button>
          </span>
        </h3>
        {overview_html}{answer_html}
        {cards}
      </div>'''


def mondai_section_html(mondai_idx, mondai_label, question_blocks_html):
    scope_id = f"m-{mondai_idx}"
    return f'''
    <section class="mondai-section" id="{scope_id}" data-scope="mondai">
      <h2>{html.escape(mondai_label)}
        <span class="scope-controls">
          <button class="scope-btn m-play" title="播放整个问题">▶ 播放整个问题</button>
          <button class="scope-btn m-loop" title="循环整个问题">⟲ 循环整个问题</button>
        </span>
      </h2>
      {question_blocks_html}
    </section>'''


PAGE_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="robots" content="noindex, nofollow" />
<title>{title}</title>
<link rel="stylesheet" href="/css/style.css" />
<style>
  .seg-card {{
    background: #fff; border: 1px solid var(--border); border-radius: var(--radius);
    padding: 16px 18px; margin-bottom: 12px; box-shadow: var(--shadow-xs);
  }}
  .seg-head {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; flex-wrap: wrap; gap: 8px; }}
  .seg-num {{
    display: inline-flex; align-items: center; justify-content: center;
    min-width: 32px; height: 24px; padding: 0 6px; border-radius: 999px; background: var(--blue-xlight);
    color: var(--blue-dark); font-size: 11px; font-weight: 700;
  }}
  .seg-controls, .scope-controls {{ display: flex; gap: 6px; flex-wrap: wrap; }}
  .scope-controls {{ display: inline-flex; margin-left: 12px; vertical-align: middle; }}
  .seg-btn, .scope-btn {{
    border: 1px solid var(--border); background: var(--bg-soft); color: var(--text);
    border-radius: 999px; padding: 4px 12px; font-size: 12px; cursor: pointer;
    transition: background .15s, border-color .15s; font-weight: 500;
  }}
  .scope-btn {{ font-size: 12px; }}
  .seg-btn:hover, .scope-btn:hover {{ background: var(--blue-xlight); border-color: var(--blue-light); }}
  .seg-btn.active, .scope-btn.active {{ background: var(--blue); border-color: var(--blue); color: #fff; }}
  .seg-ja {{ font-size: 16px; line-height: 2.3; margin: 4px 0 8px; }}
  .seg-ja ruby rt {{ font-size: 10px; color: var(--text-muted); font-style: normal; }}
  .seg-zh {{ color: var(--text-muted); font-size: 13px; font-style: italic; margin: 0 0 8px; }}
  .seg-notes {{
    font-size: 12.5px; line-height: 1.75; color: var(--text);
    background: var(--blue-xlight); border-left: 3px solid var(--blue);
    border-radius: 0 6px 6px 0; padding: 8px 12px;
  }}
  .q-overview {{ color: var(--text-muted); font-size: 14px; margin: 4px 0 14px; }}
  .seg-answer {{ margin: 0 0 16px; font-size: 13px; }}
  .seg-answer summary {{ cursor: pointer; color: var(--blue-dark); font-weight: 600; user-select: none; }}
  .seg-answer div {{
    margin-top: 8px; padding: 10px 14px; background: #fff7ed;
    border-left: 3px solid #f59e0b; border-radius: 0 6px 6px 0; line-height: 1.7;
  }}
  audio {{ display: none; }}
  .mondai-section {{ margin-bottom: 12px; }}
  .question-block {{ margin: 24px 0 32px; scroll-margin-top: 90px; }}
  .post-body h2 {{ scroll-margin-top: 90px; }}

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
    <h2>&#128274; 输入密码查看内容</h2>
    <input type="password" id="pwdInput" placeholder="密码" autofocus />
    <button id="pwdBtn">进入</button>
    <div class="err" id="pwdErr"></div>
  </div>
</div>

<div id="content">
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
    if (!document.getElementById("toc-script")) {{
      var s = document.createElement("script");
      s.id = "toc-script";
      s.src = "/js/toc.js";
      document.body.appendChild(s);
    }}
  }}
  async function tryUnlock(pwd) {{
    var h = await sha256(pwd);
    if (h === HASH) {{
      afterUnlock();
      sessionStorage.setItem("unlocked-" + location.pathname, "1");
    }} else {{
      document.getElementById("pwdErr").textContent = "密码错误";
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

// ── 三层播放控制：逐句 / 小题整体 / 大题整体，全局只允许一路在播 ──
(function() {{
  var activeSeq = null;   // {{ audios: [...], idx, loop, stop() }}
  var activeSingle = null; // 当前用"单句播放"按钮播放的 <audio>
  var allPlayBtns = [];    // 所有会改变自身文案/状态的按钮，方便统一复位

  function resetAllButtons() {{
    document.querySelectorAll(".seg-btn.play").forEach(function(b) {{ b.textContent = "▶ 播放"; }});
    document.querySelectorAll(".scope-btn").forEach(function(b) {{ b.classList.remove("active"); }});
  }}

  function stopEverything() {{
    if (activeSeq) {{ activeSeq.stop(); activeSeq = null; }}
    if (activeSingle) {{ activeSingle.pause(); activeSingle = null; }}
    resetAllButtons();
  }}

  function playSequence(audios, loop, btn) {{
    stopEverything();
    if (!audios.length) return;
    var idx = 0;
    var seq = {{ stopped: false }};
    seq.stop = function() {{
      seq.stopped = true;
      audios.forEach(function(a) {{ a.onended = null; a.pause(); }});
    }};
    function playNext() {{
      if (seq.stopped) return;
      if (idx >= audios.length) {{
        if (loop) {{ idx = 0; }} else {{ activeSeq = null; resetAllButtons(); return; }}
      }}
      var a = audios[idx];
      a.currentTime = 0;
      a.onended = function() {{ idx++; playNext(); }};
      a.play();
      idx++;
    }}
    activeSeq = seq;
    if (btn) btn.classList.add("active");
    playNext();
  }}

  document.querySelectorAll(".seg-card").forEach(function(card) {{
    var audio = card.querySelector("audio");
    var playBtn = card.querySelector(".play");
    var replayBtn = card.querySelector(".replay");
    var loopBtn = card.querySelector(".loop");

    playBtn.addEventListener("click", function() {{
      if (activeSingle === audio && !audio.paused) {{
        audio.pause();
        activeSingle = null;
        playBtn.textContent = "▶ 播放";
        return;
      }}
      stopEverything();
      activeSingle = audio;
      audio.play();
      playBtn.textContent = "⏸ 暂停";
    }});
    audio.addEventListener("ended", function() {{
      if (!audio.loop && activeSingle === audio) {{ playBtn.textContent = "▶ 播放"; activeSingle = null; }}
    }});
    replayBtn.addEventListener("click", function() {{
      stopEverything();
      activeSingle = audio;
      audio.currentTime = 0;
      audio.play();
      playBtn.textContent = "⏸ 暂停";
    }});
    loopBtn.addEventListener("click", function() {{
      audio.loop = !audio.loop;
      loopBtn.classList.toggle("active", audio.loop);
    }});
  }});

  document.querySelectorAll('.question-block[data-scope="question"]').forEach(function(block) {{
    var playBtn = block.querySelector(".q-play");
    var loopBtn = block.querySelector(".q-loop");
    function getAudios() {{ return Array.from(block.querySelectorAll("audio")); }}
    playBtn.addEventListener("click", function() {{
      playSequence(getAudios(), false, playBtn);
    }});
    loopBtn.addEventListener("click", function() {{
      playSequence(getAudios(), true, loopBtn);
    }});
  }});

  document.querySelectorAll('.mondai-section[data-scope="mondai"]').forEach(function(section) {{
    var playBtn = section.querySelector(".m-play");
    var loopBtn = section.querySelector(".m-loop");
    function getAudios() {{ return Array.from(section.querySelectorAll("audio")); }}
    playBtn.addEventListener("click", function() {{
      playSequence(getAudios(), false, playBtn);
    }});
    loopBtn.addEventListener("click", function() {{
      playSequence(getAudios(), true, loopBtn);
    }});
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
    for mi, mrec in enumerate(by_mondai, 1):
        q_blocks = []
        for qi, qrec in enumerate(mrec["questions"], 1):
            meta = overview_map.get((mrec["mondai"], qrec["question"]), {})
            q_blocks.append(question_block_html(
                mi, qi, qrec["question"] or mrec["mondai"],
                meta.get("overview", ""), meta.get("answer", ""),
                qrec["sentences"], audio_rel
            ))
        sections.append(mondai_section_html(mi, mrec["mondai"], "\n".join(q_blocks)))
    return "\n".join(sections)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("enriched_json")
    ap.add_argument("out_dir")
    ap.add_argument("--title", required=True)
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--password", required=True)
    args = ap.parse_args()

    with open(args.enriched_json, encoding="utf-8") as f:
        data = json.load(f)
    sentences = data["sentences"]
    questions = data.get("questions", [])

    os.makedirs(args.out_dir, exist_ok=True)
    audio_out_dir = os.path.join(args.out_dir, "audio")
    cut_segments(args.audio, sentences, audio_out_dir)

    sections = build_sections_html(sentences, questions, "audio/")
    pwd_hash = hashlib.sha256(args.password.encode("utf-8")).hexdigest()

    page = PAGE_TEMPLATE.format(
        title=html.escape(args.title),
        subtitle=args.subtitle,
        sections=sections,
        pwd_hash=pwd_hash,
    )

    out_html = os.path.join(args.out_dir, "index.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"Wrote {out_html} and {len(sentences)} audio clips to {audio_out_dir}")


if __name__ == "__main__":
    main()
