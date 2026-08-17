# -*- coding: utf-8 -*-
"""
用法：
  python build_boundary_editor.py <docs/private/<slug>> <tab的mondai名，比如"会话"/"生词">
      [--out <输出目录，默认 tools/listening/work/<slug>/boundary_editor_<tab>/>]

共享工具（`jp-textbook-lesson` 用）：给"人工拖拽边界"这个工作流准备数据——
从**当前已发布**的 `data.js` + `audio/seg-NNN.mp3` 出发（不依赖任何work目录里
可能过期的 `enriched.json`，永远反映真实线上状态），对指定 tab 的每个句子/
生词条目：
  1. `ffprobe` 量出实际时长，拼出精确累计边界（这一步跟本课这次人工排查
     "15课会话第2节尾音过长"反馈时用的方法完全一样）。
  2. 把该 tab 全部 clip 无损拼接成一份连续音频（`merged.mp3`）。
  3. 连同每条的 id/文字，写成 `manifest.json`。
  4. 把配套的 `boundary_editor.html`（跟本脚本同目录，通用不用改）复制进
     输出目录——两个文件放在一起，用 `npx http-server <输出目录>` 直接起
     本地服务器打开就能用，同目录相对路径 `fetch('manifest.json')`/
     `fetch('merged.mp3')` 不用配置任何东西。

产出目录只用来这一轮编辑，改完导出的 JSON 交给 `apply_boundary_edits.py`
处理时还会再读一次这份 `manifest.json`/`merged.mp3` 当作重切音频的源——
这中间**不要**手工再跑一次 `build_page.py` 或者动 `audio/` 目录，不然
这份 manifest 记录的边界就跟磁盘上的真实内容对不上了，重切会切错。
"""
import sys
import os
import re
import json
import shutil
import argparse
import subprocess
import imageio_ffmpeg

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FFPROBE = FFMPEG.replace("ffmpeg", "ffprobe") if "ffprobe" not in FFMPEG else FFMPEG


def ffprobe_duration(path):
    for exe in (FFPROBE, "ffprobe"):
        try:
            r = subprocess.run(
                [exe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            if r.returncode == 0 and r.stdout.strip():
                return float(r.stdout.strip())
        except FileNotFoundError:
            continue
    raise RuntimeError(f"ffprobe 拿不到时长: {path}")


def load_lesson_data(slug_dir):
    data_js = os.path.join(slug_dir, "data.js")
    content = open(data_js, encoding="utf-8").read()
    m = re.match(r"^\s*window\.LESSON_DATA\s*=\s*(.*);\s*$", content, re.S)
    if not m:
        raise RuntimeError(f"{data_js} 不是预期的 `window.LESSON_DATA = {{...}};` 格式，没法解析")
    return json.loads(m.group(1))


def sentence_text(s):
    return "".join(t.get("text", "") for t in s.get("tokens", []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug_dir", help="docs/private/<slug>")
    ap.add_argument("tab", help='tab的mondai名，比如 "会话"/"课文"/"生词"')
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    slug_dir = args.slug_dir.rstrip("/\\")
    slug = os.path.basename(slug_dir)
    data = load_lesson_data(slug_dir)

    tabs = [t for t in data["tabs"] if t.get("mondai") == args.tab]
    if not tabs:
        available = [t.get("mondai") for t in data["tabs"]]
        print(f"FAIL: 找不到 mondai=={args.tab!r} 的 tab，这一课实际有: {available}")
        sys.exit(1)
    tab = tabs[0]
    has_token_timing = args.tab != "生词"  # 生词条目没有 tokens[].t，见脚本文档字符串

    sentences = []
    for q in tab["questions"]:
        for s in q["sentences"]:
            sentences.append(s)
    sentences.sort(key=lambda s: s["id"])
    if not sentences:
        print("FAIL: 这个tab没有任何句子/条目")
        sys.exit(1)

    audio_dir = os.path.join(slug_dir, "audio")
    out_dir = args.out or os.path.join(
        "tools", "listening", "work", slug, f"boundary_editor_{args.tab}"
    )
    os.makedirs(out_dir, exist_ok=True)

    list_path = os.path.join(out_dir, "concat_list.txt")
    manifest_sentences = []
    cur = 0.0
    missing = []
    with open(list_path, "w", encoding="utf-8") as lf:
        for s in sentences:
            audio_rel = s.get("audio")
            if not audio_rel:
                missing.append(s["id"])
                continue
            p = os.path.abspath(os.path.join(slug_dir, audio_rel))
            if not os.path.exists(p):
                missing.append(s["id"])
                continue
            dur = ffprobe_duration(p)
            lf.write(f"file '{p.replace(chr(92), '/')}'\n")
            manifest_sentences.append({
                "id": s["id"],
                "text": sentence_text(s) or (s.get("blanks") or [""])[0],
                "start": round(cur, 3),
                "end": round(cur + dur, 3),
            })
            cur += dur

    if missing:
        print(f"警告：{len(missing)} 条没有音频文件被跳过（id: {missing}），"
              f"这些不会出现在编辑器里")

    merged_path = os.path.join(out_dir, "merged.mp3")
    subprocess.run(
        [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", os.path.abspath(list_path),
         "-ar", "48000", "-ac", "1", "-b:a", "128k", merged_path],
        capture_output=True
    )
    if not os.path.exists(merged_path) or os.path.getsize(merged_path) < 1000:
        print("FAIL: merged.mp3 没生成成功，检查上面 concat_list.txt 里的路径是否都存在")
        sys.exit(1)

    manifest = {
        "slug": slug,
        "tab": args.tab,
        "hasTokenTiming": has_token_timing,
        "totalDuration": round(cur, 3),
        "sentences": manifest_sentences,
    }
    manifest_path = os.path.join(out_dir, "manifest.json")
    json.dump(manifest, open(manifest_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    html_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "boundary_editor.html")
    if os.path.exists(html_src):
        shutil.copy(html_src, os.path.join(out_dir, "boundary_editor.html"))
    else:
        print(f"警告：{html_src} 不存在，只生成了数据，还没有编辑器页面本身")

    print(f"生成完成：{len(manifest_sentences)} 条，总时长 {cur:.1f}s")
    print(f"输出目录：{out_dir}")
    print(f"本地起服务器打开：npx http-server \"{out_dir}\" -p 8080 然后浏览器开 "
          f"http://127.0.0.1:8080/boundary_editor.html")


if __name__ == "__main__":
    main()
