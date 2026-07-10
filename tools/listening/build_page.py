# -*- coding: utf-8 -*-
"""
用法：
  python build_page.py <原始音频> <enriched.json 已填好zh/notes> <输出目录>
      --title "标题" --subtitle "副标题" --password sairai

<输出目录> 会生成：
  index.html      密码门 + noindex + 逐句播放/重放/循环 的听力页
  audio/seg-NN.mp3  每句切出来的音频片段

生成后把 <输出目录> 放到 docs/private/<slug>/ 下即可通过个人网站访问，
但不要把它加进 blog/index.html、posts.json 或站内导航——保持"不公开链接"。
"""
import sys
import os
import json
import html
import hashlib
import argparse
import subprocess
import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def cut_segments(audio_path, segs, out_audio_dir):
    os.makedirs(out_audio_dir, exist_ok=True)
    for seg in segs:
        out_file = os.path.join(out_audio_dir, f"seg-{seg['id']:02d}.mp3")
        dur = seg["end"] - seg["start"]
        subprocess.run(
            [FFMPEG, "-y", "-ss", str(seg["start"]), "-t", str(dur), "-i", audio_path,
             "-ar", "44100", "-ac", "1", "-b:a", "96k", out_file],
            capture_output=True
        )


def card_html(seg, audio_rel):
    label = seg.get("label", "")
    num_display = html.escape(label) if label else f"{seg['id']:02d}"
    zh = html.escape(seg["zh"]).replace("\n", "<br>")
    answer_html = ""
    if seg.get("answer"):
        answer_html = f'''
        <details class="seg-answer">
          <summary>点击查看答案</summary>
          <div>{html.escape(seg['answer'])}</div>
        </details>'''
    return f'''
      <div class="seg-card">
        <div class="seg-head">
          <span class="seg-num">{num_display}</span>
          <div class="seg-controls">
            <button class="seg-btn play" data-target="a{seg['id']}" title="播放/暂停">▶ 播放</button>
            <button class="seg-btn replay" data-target="a{seg['id']}" title="从头重放">↺ 重放</button>
            <button class="seg-btn loop" data-target="a{seg['id']}" title="单句循环">⟲ 循环</button>
          </div>
        </div>
        <p class="seg-ja">{seg['furigana']}</p>
        <p class="seg-zh">{zh}</p>
        <div class="seg-notes">{html.escape(seg['notes'])}</div>{answer_html}
        <audio id="a{seg['id']}" preload="none" src="{audio_rel}seg-{seg['id']:02d}.mp3"></audio>
      </div>'''


def group_header_html(group):
    return f'<h2 class="mondai-header">{html.escape(group)}</h2>'


PAGE_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="robots" content="noindex, nofollow" />
<title>{title}</title>
<style>
  :root {{
    --navy: #0c1445; --blue: #2563eb; --blue-dark: #1d4ed8;
    --blue-light: #dbeafe; --blue-xlight: #eff6ff;
    --text: #0f172a; --text-muted: #64748b;
    --bg: #ffffff; --bg-soft: #f8fafc;
    --border: #e2e8f0; --radius: 10px;
    --shadow: 0 4px 20px rgba(0,0,0,0.09), 0 1px 4px rgba(0,0,0,0.05);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg-soft); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
  }}
  .wrap {{ max-width: 760px; margin: 0 auto; padding: 40px 20px 80px; }}
  h1 {{ font-size: 24px; margin: 0 0 6px; }}
  .subtitle {{ color: var(--text-muted); font-size: 14px; margin: 0 0 28px; line-height: 1.7; }}
  .seg-card {{
    background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 18px 20px; margin-bottom: 16px; box-shadow: var(--shadow);
  }}
  .seg-head {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; flex-wrap: wrap; gap: 8px; }}
  .seg-num {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 28px; height: 28px; border-radius: 50%; background: var(--blue-xlight);
    color: var(--blue-dark); font-size: 12px; font-weight: 700;
  }}
  .seg-controls {{ display: flex; gap: 6px; }}
  .seg-btn {{
    border: 1px solid var(--border); background: var(--bg-soft); color: var(--text);
    border-radius: 999px; padding: 5px 12px; font-size: 12px; cursor: pointer;
    transition: background .15s, border-color .15s;
  }}
  .seg-btn:hover {{ background: var(--blue-xlight); border-color: var(--blue-light); }}
  .seg-btn.active {{ background: var(--blue); border-color: var(--blue); color: #fff; }}
  .seg-ja {{ font-size: 17px; line-height: 2.4; margin: 4px 0 8px; }}
  .seg-ja ruby rt {{ font-size: 11px; color: var(--text-muted); font-style: normal; }}
  .seg-zh {{ color: var(--text-muted); font-size: 14px; font-style: italic; margin: 0 0 10px; }}
  .seg-notes {{
    font-size: 13px; line-height: 1.8; color: var(--text);
    background: var(--blue-xlight); border-left: 3px solid var(--blue);
    border-radius: 0 6px 6px 0; padding: 10px 14px;
  }}
  .mondai-header {{
    font-size: 16px; color: var(--blue-dark); margin: 36px 0 14px;
    padding-bottom: 6px; border-bottom: 2px solid var(--blue-light);
  }}
  .mondai-header:first-of-type {{ margin-top: 4px; }}
  .seg-answer {{ margin-top: 10px; font-size: 13px; }}
  .seg-answer summary {{
    cursor: pointer; color: var(--blue-dark); font-weight: 600; user-select: none;
  }}
  .seg-answer div {{
    margin-top: 8px; padding: 10px 14px; background: #fff7ed;
    border-left: 3px solid var(--gold, #f59e0b); border-radius: 0 6px 6px 0; line-height: 1.7;
  }}
  audio {{ display: none; }}
  #gate {{
    position: fixed; inset: 0; background: var(--navy); display: flex;
    align-items: center; justify-content: center; z-index: 999; flex-direction: column;
  }}
  #gate .box {{
    background: #fff; border-radius: 14px; padding: 32px 28px; width: 300px;
    text-align: center; box-shadow: var(--shadow);
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
  <div class="wrap">
    <h1>{title}</h1>
    <p class="subtitle">{subtitle}</p>
    {cards}
  </div>
</div>

<script>
(function() {{
  var HASH = "{pwd_hash}";
  async function sha256(str) {{
    var buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(str));
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
  }}
  async function tryUnlock(pwd) {{
    var h = await sha256(pwd);
    if (h === HASH) {{
      document.getElementById("gate").style.display = "none";
      document.getElementById("content").style.display = "block";
      sessionStorage.setItem("unlocked-" + location.pathname, "1");
    }} else {{
      document.getElementById("pwdErr").textContent = "密码错误";
    }}
  }}
  if (sessionStorage.getItem("unlocked-" + location.pathname) === "1") {{
    document.getElementById("gate").style.display = "none";
    document.getElementById("content").style.display = "block";
  }}
  document.getElementById("pwdBtn").addEventListener("click", function() {{
    tryUnlock(document.getElementById("pwdInput").value);
  }});
  document.getElementById("pwdInput").addEventListener("keydown", function(e) {{
    if (e.key === "Enter") tryUnlock(this.value);
  }});
}})();

document.querySelectorAll(".seg-card").forEach(function(card) {{
  var audio = card.querySelector("audio");
  var playBtn = card.querySelector(".play");
  var replayBtn = card.querySelector(".replay");
  var loopBtn = card.querySelector(".loop");

  playBtn.addEventListener("click", function() {{
    if (audio.paused) {{ audio.play(); playBtn.textContent = "⏸ 暂停"; }}
    else {{ audio.pause(); playBtn.textContent = "▶ 播放"; }}
  }});
  audio.addEventListener("ended", function() {{
    if (!audio.loop) playBtn.textContent = "▶ 播放";
  }});
  replayBtn.addEventListener("click", function() {{
    audio.currentTime = 0;
    audio.play();
    playBtn.textContent = "⏸ 暂停";
  }});
  loopBtn.addEventListener("click", function() {{
    audio.loop = !audio.loop;
    loopBtn.classList.toggle("active", audio.loop);
  }});
}});
</script>

</body>
</html>
'''


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
        segs = json.load(f)

    os.makedirs(args.out_dir, exist_ok=True)
    audio_out_dir = os.path.join(args.out_dir, "audio")
    cut_segments(args.audio, segs, audio_out_dir)

    parts = []
    last_group = None
    for s in segs:
        group = s.get("group")
        if group and group != last_group:
            parts.append(group_header_html(group))
            last_group = group
        parts.append(card_html(s, "audio/"))
    cards = "\n".join(parts)
    pwd_hash = hashlib.sha256(args.password.encode("utf-8")).hexdigest()

    page = PAGE_TEMPLATE.format(
        title=html.escape(args.title),
        subtitle=args.subtitle,
        cards=cards,
        pwd_hash=pwd_hash,
    )

    out_html = os.path.join(args.out_dir, "index.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"Wrote {out_html} and {len(segs)} audio clips to {audio_out_dir}")


if __name__ == "__main__":
    main()
