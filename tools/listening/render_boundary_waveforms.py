# -*- coding: utf-8 -*-
"""
用法：
  python render_boundary_waveforms.py <enriched.json> <原始音频文件> <输出目录>
      [--window-sec 25] [--width 1600] [--height 260]

共享工具（`jp-textbook-lesson` 用）：把 `verify_boundaries_rms.py` 的思路反过来——
不先靠数值脚本筛"可疑点"再挑着看图，而是把整段音频渲染成一批带边界标记的
波形图，覆盖全部时长，让人（Claude 自己）用 Read 工具逐张看完，跟用户在
`boundary_editor.html` 里肉眼判断边界的方式一致。真实背景（textbook-sjp-
zg-l14）：`audit_boundaries_rms.py`/`audit_boundaries_quietpoint.py` 这类
数值脚本本身会漏检——它们只能告诉你"这些点看起来可疑"，漏掉的点永远不会
被人工核实到。全量扫一遍波形图不依赖任何"哪些点该重点看"的预判。

## 用法上要注意

- `enriched.json` 和音频文件必须是同一个坐标系——传某个 tab 自己的
  `enriched_<tab>_final.json` + 这个 tab 自己的原始音频（不是切好的
  `seg-NNN.mp3`，也不是合并后的 `combined.m4a`/`enriched_combined.json`，
  两者坐标系不匹配，见 `audit_boundaries_rms.py` 文档同一条提醒）。
- 每张图默认覆盖 25 秒，图上每一条竖线是一个句子/生词的 start 或 end，
  线旁边标 "id·S"/"id·E"。相邻两句共享的边界（前一句 end == 下一句
  start）只画一条线，两个标签一起标在旁边。
- 生成完之后**必须用 Read 工具把 `out_dir` 里的每一张图都看一遍**，图
  本身不做任何自动判断——这是有意的：人眼扫波形陡升/陡降沿本身就是这
  个工具存在的意义，脚本只负责渲染，不负责下结论。
- 生词表（零间隔连续朗读）用默认 25 秒窗口时，密集区域标签可能重叠，
  必要时加大 `--width` 或调小 `--window-sec` 换取更高的时间分辨率。
"""
import sys
import os
import subprocess
import json
import argparse
import numpy as np
import imageio_ffmpeg
from PIL import Image, ImageDraw

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
SR = 16000


def decode_pcm(audio_path):
    proc = subprocess.run(
        [FFMPEG, "-i", audio_path, "-ar", str(SR), "-ac", "1", "-f", "s16le", "-"],
        capture_output=True
    )
    return np.frombuffer(proc.stdout, dtype=np.int16)


def collect_boundaries(enriched_json):
    data = json.load(open(enriched_json, encoding="utf-8"))
    points = {}  # time -> list of "id·S"/"id·E" labels
    for s in data["sentences"]:
        for t, tag in ((s["start"], "S"), (s["end"], "E")):
            points.setdefault(round(t, 3), []).append(f"{s['id']}{tag}")
    return points


def render_window(samples, points, w_start, w_end, width, height):
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    mid = height // 2
    draw.line([(0, mid), (width, mid)], fill=(220, 220, 220))

    i0 = int(w_start * SR)
    i1 = int(w_end * SR)
    chunk = samples[max(0, i0):max(0, i1)]
    if len(chunk):
        cols = np.array_split(chunk, width)
        amp = (height // 2) - 4
        peak = max(1, np.abs(chunk).max())
        for x, col in enumerate(cols):
            if len(col) == 0:
                continue
            lo, hi = int(col.min()), int(col.max())
            y_lo = mid - int(lo / peak * amp)
            y_hi = mid - int(hi / peak * amp)
            draw.line([(x, min(y_lo, y_hi)), (x, max(y_lo, y_hi))], fill=(70, 110, 170))

    label_row_h = 12
    boundaries_in_window = sorted(t for t in points if w_start <= t <= w_end)
    for idx, t in enumerate(boundaries_in_window):
        x = int((t - w_start) / (w_end - w_start) * width)
        labels = points[t]
        is_end_only = all(l.endswith("E") for l in labels)
        color = (200, 40, 40) if is_end_only else (30, 140, 60)
        draw.line([(x, 0), (x, height)], fill=color, width=1)
        row = idx % 3
        y = 2 + row * label_row_h
        text = ",".join(labels)
        draw.text((min(x + 2, width - 8 * len(text)), y), text, fill=color)

    draw.text((4, height - 12), f"{w_start:.2f}s ~ {w_end:.2f}s", fill=(120, 120, 120))
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("enriched_json")
    ap.add_argument("audio_path")
    ap.add_argument("out_dir")
    ap.add_argument("--window-sec", type=float, default=25.0)
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=260)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    samples = decode_pcm(args.audio_path)
    duration = len(samples) / SR
    points = collect_boundaries(args.enriched_json)

    n_windows = int(duration // args.window_sec) + 1
    written = []
    w_start = 0.0
    idx = 0
    while w_start < duration:
        w_end = min(w_start + args.window_sec, duration)
        img = render_window(samples, points, w_start, w_end, args.width, args.height)
        fname = f"wf_{idx:02d}_{w_start:07.2f}-{w_end:07.2f}.png"
        path = os.path.join(args.out_dir, fname)
        img.save(path)
        written.append(path)
        w_start = w_end
        idx += 1

    total_boundaries = len(points)
    print(f"音频时长 {duration:.1f}s，共 {total_boundaries} 个边界点，"
          f"生成 {len(written)} 张图到 {args.out_dir}：")
    for p in written:
        print(" ", p)


if __name__ == "__main__":
    main()
