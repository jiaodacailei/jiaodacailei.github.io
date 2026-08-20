# -*- coding: utf-8 -*-
"""
用法：
  python backfill_clause_bounds.py <slug> <mondai名，比如"会话"/"课文">
      [--fix] [--work-dir <目录>]

给**已发布**的课（`docs/private/<slug>/data.js` 里已经跑过完整流程、
`tools/listening/work/<slug>/` 下的原始 `enriched_combined.json`/合并音频
可能已经被清理或者有好几个互相矛盾的版本）补跑 `compute_clause_bounds.py`
——不依赖 work 目录里任何可能过期/有歧义的中间文件，直接从**当前真正线上
的内容**重建一份等价的输入：

1. 把这个 tab 下所有句子已经发布的 `audio/seg-NNN.mp3` 按顺序无损拼接成一份
   连续音频（同 `build_boundary_editor.py` 的做法）——这份音频保证跟当前
   `data.js` 记录的内容完全一致，不会有"哪个版本才是最终版"的歧义。
2. 每句的 `char_times`（`compute_clause_bounds.py` 需要的、跟 `text` 等长
   的逐字符时间戳数组）用 `data.js` 里已经发布的 `tokens[].t` 重建——每个
   token 覆盖几个字符，这几个字符就都沿用这个 token 自己的 `t`。这比原始
   （生成时）的逐字符 `char_times` 粗一些（一个 token 内部的字符已经拿不到
   各自独立的时间戳了），但 `compute_clause_bounds.py` 只用
   `char_times[逗号后一个字符]` 当粗略候选位置——逗号在 `tokenize_ja()` 的
   输出里几乎总是独立成一个 token（前后字符时间戳不同，不会被合并步骤并
   进邻居），这个值等于紧跟着的下一个 token 自己的 `t`，跟原始精度是等价
   的，不影响算法准确性。

跟 `compute_clause_bounds.py` 一样先只出报告，看着没问题再加 `--fix` 写回
`docs/private/<slug>/data.js` 的 `clauseBounds` 字段（换算回每句自己 clip
的相对时间）。中间产物（拼接音频、报告）留在
`tools/listening/work/<slug>/clause_backfill_<tab>/` 下，方便回查。
"""
import sys
import os
import re
import json
import argparse
import subprocess
import imageio_ffmpeg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compute_clause_bounds import find_clause_bounds_for_sentence, count_clause_punct
from build_boundary_editor import ffprobe_duration

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_lesson_data(slug_dir):
    data_js = os.path.join(slug_dir, "data.js")
    content = open(data_js, encoding="utf-8").read()
    m = re.match(r"^\s*window\.LESSON_DATA\s*=\s*(.*);\s*$", content, re.S)
    if not m:
        raise RuntimeError(f"{data_js} 不是预期的 `window.LESSON_DATA = {{...}};` 格式")
    return json.loads(m.group(1))


def save_lesson_data(slug_dir, data):
    data_js = os.path.join(slug_dir, "data.js")
    with open(data_js, "w", encoding="utf-8") as f:
        f.write("window.LESSON_DATA = ")
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write(";\n")


def reconstruct_char_times(s, sentence_start_abs):
    """见文件文档字符串——每个字符沿用它所属 token 自己的绝对时间戳
    （sentence_start_abs + token['t']），没有 't' 的 token（比如换行符）
    对应位置留 None。"""
    chars = []
    times = []
    for tok in s.get("tokens", []):
        text = tok.get("text", "")
        t = tok.get("t")
        abs_t = round(sentence_start_abs + t, 3) if t is not None else None
        for ch in text:
            chars.append(ch)
            times.append(abs_t)
    return "".join(chars), times


class _Args:
    """喂给 find_clause_bounds_for_sentence() 的参数对象，用跟
    compute_clause_bounds.py CLI 完全一样的默认值，保证同一套判据。"""
    search_back = 0.4
    search_front = 0.4
    frame_ms = 5
    min_rise = 6.0
    quiet_ceiling = -28.0  # 见 compute_clause_bounds.py 文档字符串里对这个默认值改动的详细说明
    margin = -0.02  # 见 compute_clause_bounds.py 文档字符串里对这个默认值改动的详细说明


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("tab")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--work-dir", default=None)
    args = ap.parse_args()

    slug_dir = os.path.join(REPO_ROOT, "docs", "private", args.slug)
    data = load_lesson_data(slug_dir)
    tabs = [t for t in data["tabs"] if t.get("mondai") == args.tab]
    if not tabs:
        available = [t.get("mondai") for t in data["tabs"]]
        print(f"FAIL: 找不到 mondai=={args.tab!r} 的 tab，这一课实际有: {available}")
        sys.exit(1)
    tab = tabs[0]

    sentences = []
    for q in tab["questions"]:
        sentences.extend(q["sentences"])
    sentences.sort(key=lambda s: s["id"])
    id_to_sentence = {s["id"]: s for s in sentences}

    work_dir = args.work_dir or os.path.join(
        REPO_ROOT, "tools", "listening", "work", args.slug, f"clause_backfill_{args.tab}"
    )
    os.makedirs(work_dir, exist_ok=True)

    list_path = os.path.join(work_dir, "concat_list.txt")
    synth_sentences = []
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
            entry = {"id": s["id"], "start": round(cur, 3), "end": round(cur + dur, 3)}
            has_timing = any(t.get("t") is not None for t in s.get("tokens", []))
            if has_timing:
                text, char_times = reconstruct_char_times(s, cur)
                entry["text"] = text
                entry["char_times"] = char_times
            synth_sentences.append(entry)
            cur += dur

    if missing:
        print(f"警告：{len(missing)} 条没有音频文件被跳过（id: {missing}）")
    if not synth_sentences:
        print("FAIL: 这个tab没有任何可用的句子/音频")
        sys.exit(1)

    merged_path = os.path.join(work_dir, "merged.wav")
    subprocess.run(
        [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", os.path.abspath(list_path),
         "-ar", "44100", "-ac", "1", merged_path],
        capture_output=True
    )
    if not os.path.exists(merged_path) or os.path.getsize(merged_path) < 1000:
        print("FAIL: merged.wav 没生成成功，检查 concat_list.txt 里的路径是否都存在")
        sys.exit(1)

    lines = []
    total_commas = 0
    total_bounds = 0
    fixed_ids = []
    for entry in synth_sentences:
        if "char_times" not in entry:
            continue
        commas = count_clause_punct(entry["text"])
        if commas == 0:
            continue
        bounds, skipped = find_clause_bounds_for_sentence(merged_path, entry, _Args)
        total_commas += commas
        total_bounds += len(bounds)
        lines.append(f'{entry["id"]:4d} {entry["text"][:30]:30s} 逗号{commas}处 -> clauseBounds={bounds}')
        for i, rough_t, reason in skipped:
            rough_t_str = f'{rough_t:.2f}' if rough_t is not None else 'None'
            lines.append(f'         跳过第{i}处逗号 (rough_t={rough_t_str}): {reason}')
        if args.fix and bounds:
            s = id_to_sentence[entry["id"]]
            s["clauseBounds"] = [round(t - entry["start"], 2) for t in bounds]
            fixed_ids.append(entry["id"])

    summary = f"共{len(synth_sentences)}句，{total_commas}处逗号，找到{total_bounds}处确信分句边界"
    out = "\n".join(lines) + "\n\n" + summary + "\n"
    report_path = os.path.join(work_dir, "report.txt")
    open(report_path, "w", encoding="utf-8").write(out)
    print(out)
    print(f"报告写入 {report_path}")

    if args.fix:
        save_lesson_data(slug_dir, data)
        print(f"--fix：已把 {len(fixed_ids)} 句的 clauseBounds 写回 {os.path.join(slug_dir, 'data.js')}")


if __name__ == "__main__":
    main()
