# -*- coding: utf-8 -*-
"""
用法：
  python apply_boundary_edits.py <docs/private/<slug>> <edits.json>

共享工具（`jp-textbook-lesson` 用）：`boundary_editor.html`（配合
`build_boundary_editor.py` 生成的数据）导出的 JSON，用这个脚本落地——
根据人工拖拽后的新边界时间，从编辑时用的同一份 `merged.mp3`（在
`tools/listening/work/<slug>/boundary_editor_<tab>/` 下）重切受影响的
`audio/seg-NNN.mp3`，并且（如果这个tab的句子带 `tokens[].t` 跟读高亮
时间戳——生词表没有，会话/课文有）把因为"起点变了"而需要平移的
token 时间戳同步进 `data.js`。

`edits.json` 格式（`boundary_editor.html` 导出的原样格式）：
  {
    "slug": "textbook-sjp-zg-l15",
    "tab": "会话",
    "edits": [
      {"beforeId": 13, "afterId": 14, "newBoundary": 29.98},
      ...
    ]
  }

每条 edit 只描述"这一个边界改到了哪"，不用调用方自己换算受影响的两个
id 各自新的 start/end——脚本从 `manifest.json` 里已经算好的原始边界
出发，把全部 edits 应用一遍，再统一算出这一轮总共有哪些 id 的 start
或 end 真的变了（同一个 id 左右两侧都被单独编辑到也能正确处理）。

跑完之后**仍然要走 SKILL.md 规定的最终验证**（`audit_boundaries_
quietpoint.py` + 拼接转写）——这个脚本只保证"按你标的新边界忠实切"，
不检查新边界本身选得对不对，那是人工在编辑器里拖的时候自己听着定的。
"""
import sys
import os
import re
import json
import argparse
import subprocess
import imageio_ffmpeg

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def probe_format(path):
    """探测已有音频文件的采样率/声道/码率，让重切出来的文件参数保持一致。"""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels,bit_rate",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    lines = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
    sr, ch, br = (lines + ["48000", "1", "128000"])[:3]
    return sr, ch, (br if br.isdigit() else "128000")


def load_lesson_data(slug_dir):
    data_js = os.path.join(slug_dir, "data.js")
    content = open(data_js, encoding="utf-8").read()
    m = re.match(r"^\s*window\.LESSON_DATA\s*=\s*(.*);\s*$", content, re.S)
    if not m:
        raise RuntimeError(f"{data_js} 不是预期的 `window.LESSON_DATA = {{...}};` 格式")
    return json.loads(m.group(1)), content


def save_lesson_data(slug_dir, data):
    data_js = os.path.join(slug_dir, "data.js")
    with open(data_js, "w", encoding="utf-8") as f:
        f.write("window.LESSON_DATA = ")
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write(";\n")


def find_sentence(data, tab_name, sid):
    for t in data["tabs"]:
        if t.get("mondai") != tab_name:
            continue
        for q in t["questions"]:
            for s in q["sentences"]:
                if s["id"] == sid:
                    return s
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug_dir", help="docs/private/<slug>")
    ap.add_argument("edits_json", help="boundary_editor.html 导出的 json 文件路径")
    ap.add_argument("--work-dir", default=None,
                     help="manifest.json/merged.mp3 所在目录，默认 tools/listening/work/<slug>/"
                          "boundary_editor_<tab>/（只有当 build_boundary_editor.py 当初用了自定义 "
                          "--out 才需要传这个）")
    args = ap.parse_args()

    slug_dir = args.slug_dir.rstrip("/\\")
    slug = os.path.basename(slug_dir)
    payload = json.load(open(args.edits_json, encoding="utf-8"))
    tab = payload["tab"]
    edits = payload["edits"]
    if not edits:
        print("edits 是空的，没有要处理的改动")
        return

    work_dir = args.work_dir or os.path.join("tools", "listening", "work", slug, f"boundary_editor_{tab}")
    manifest_path = os.path.join(work_dir, "manifest.json")
    merged_path = os.path.join(work_dir, "merged.mp3")
    if not os.path.exists(manifest_path) or not os.path.exists(merged_path):
        print(f"FAIL: 找不到 {manifest_path} 或 {merged_path}——先跑 build_boundary_editor.py "
              f"{slug_dir} {tab} 重新生成一份，再打开编辑器改（不要用一份已经不在了的旧 manifest）")
        sys.exit(1)

    manifest = json.load(open(manifest_path, encoding="utf-8"))
    if manifest.get("slug") != slug or manifest.get("tab") != tab:
        print(f"警告：manifest 里记录的是 {manifest.get('slug')}/{manifest.get('tab')}，"
              f"跟传入的 {slug}/{tab} 不一致，继续按传入参数处理")

    by_id = {s["id"]: dict(s) for s in manifest["sentences"]}  # 当前(=编辑前)的 start/end
    original_by_id = {s["id"]: (s["start"], s["end"]) for s in manifest["sentences"]}

    missing_ids = []
    for e in edits:
        bid, aid, nb = e["beforeId"], e["afterId"], e["newBoundary"]
        if bid not in by_id or aid not in by_id:
            missing_ids.append((bid, aid))
            continue
        by_id[bid]["end"] = nb
        by_id[aid]["start"] = nb

    if missing_ids:
        print(f"FAIL: 这些边界引用的 id 在 manifest 里找不到（先重新生成一遍 manifest 再改）: {missing_ids}")
        sys.exit(1)

    touched_ids = sorted({
        sid for sid, (ostart, oend) in original_by_id.items()
        if by_id[sid]["start"] != ostart or by_id[sid]["end"] != oend
    })
    if not touched_ids:
        print("所有 edits 应用后跟原始边界一样，没有需要重切的文件")
        return

    audio_dir = os.path.join(slug_dir, "audio")
    example_file = None
    for sid in touched_ids:
        p = os.path.join(audio_dir, f"seg-{sid:03d}.mp3")
        if os.path.exists(p):
            example_file = p
            break
    sr, ch, br = probe_format(example_file) if example_file else ("48000", "1", "128000")

    data, _ = load_lesson_data(slug_dir)
    has_token_timing = manifest.get("hasTokenTiming", tab != "生词")

    print(f"共 {len(touched_ids)} 个 id 需要重切: {touched_ids}")
    for sid in touched_ids:
        old_start, old_end = original_by_id[sid]
        new_start, new_end = by_id[sid]["start"], by_id[sid]["end"]
        if new_end <= new_start:
            print(f"FAIL: id {sid} 算出来的新区间 [{new_start}, {new_end}] 不合法（起点>=终点），中止")
            sys.exit(1)
        out = os.path.join(audio_dir, f"seg-{sid:03d}.mp3")
        subprocess.run(
            [FFMPEG, "-y", "-ss", str(new_start), "-t", str(new_end - new_start),
             "-i", os.path.abspath(merged_path),
             "-ar", sr, "-ac", ch, "-b:a", f"{int(br) // 1000}k" if br.isdigit() else "128k",
             out],
            capture_output=True
        )
        note = ""
        if has_token_timing and abs(new_start - old_start) > 0.0005:
            s = find_sentence(data, tab, sid)
            if s is None:
                note = "  [警告：data.js 里没找到这个id，token时间戳没能同步]"
            else:
                delta = round(new_start - old_start, 3)
                for tok in s.get("tokens", []):
                    if "t" in tok:
                        tok["t"] = round(tok["t"] + delta, 2)
                note = f"  [token时间戳整体平移 {delta:+.3f}s]"
        print(f"  id {sid}: [{old_start:.3f},{old_end:.3f}] -> [{new_start:.3f},{new_end:.3f}]{note}")

    if has_token_timing:
        save_lesson_data(slug_dir, data)
        print("data.js 已更新（token时间戳同步）")

    print("\n完成。接下来仍需按 SKILL.md 走一遍最终验证（RMS + 拼接转写）再提交。")


if __name__ == "__main__":
    main()
