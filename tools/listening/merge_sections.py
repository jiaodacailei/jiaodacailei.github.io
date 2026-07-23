# -*- coding: utf-8 -*-
"""
用法：
  python merge_sections.py <输出合并音频> <输出合并enriched.json> \
      --section <第1段原始音频> <第1段enriched_final.json> \
      --section <第2段原始音频> <第2段enriched_final.json> \
      [--section ... 可以传任意多段]

教材课文这类"每个部分各有一份独立音频"的场景专用（`jp-textbook-lesson` skill
用到）：把几段音频按传入顺序拼接成一个文件，并把各段的 `enriched_final.json`
（每段各自跑完 `refine_boundaries.py`/`validate_boundaries.py`，坐标系是各自
音频的本地时间，从0开始）按拼接后的偏移量整体平移 `start`/`end`/`char_times`，
合并成一份、重新分配连续 `id`，直接喂给 `build_page.py` 的 `<原始音频>`/
`<enriched.json>` 两个参数。

**关键前提：传进来的每份 `enriched_final.json` 必须是对着它自己那段原始音频
（不是拼接后的音频）跑完 `refine_boundaries.py` 算出来的**——那个脚本内部会
对着传入的音频文件重新截取一段做 word-level 转写，如果传的是拼接文件、
时间戳却是本地坐标系（没先平移），会截到完全无关的音频位置；这个脚本只负责
"平移+合并"这一步，音频拼接和坐标平移的顺序不能反。
"""
import sys
import os
import json
import argparse
import subprocess
import imageio_ffmpeg

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def get_duration(path):
    probe = subprocess.run([FFMPEG, "-i", path], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    lines = [l for l in probe.stderr.splitlines() if "Duration" in l]
    if not lines:
        raise RuntimeError(f"ffmpeg 探测不到时长，检查文件是不是有效音频：{path}")
    hms = lines[0].split("Duration:")[1].split(",")[0].strip()
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def shift(sentences, offset):
    out = []
    for s in sentences:
        s = dict(s)
        s["start"] = round(s["start"] + offset, 3)
        s["end"] = round(s["end"] + offset, 3)
        if s.get("char_times"):
            s["char_times"] = [round(t + offset, 3) for t in s["char_times"]]
        out.append(s)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_audio", help="拼接后的合并音频输出路径（比如 combined.m4a）")
    ap.add_argument("out_json", help="平移合并后的 enriched.json 输出路径")
    ap.add_argument("--section", nargs=2, action="append", required=True,
                     metavar=("AUDIO", "ENRICHED_JSON"),
                     help="一段的原始音频路径 + 它对应的 enriched_final.json 路径，按最终 tab 顺序传，可传多次")
    args = ap.parse_args()

    audio_paths = [a for a, _ in args.section]
    json_paths = [j for _, j in args.section]

    print("拼接音频：", " + ".join(audio_paths))
    inputs = []
    for p in audio_paths:
        inputs += ["-i", p]
    n = len(audio_paths)
    filter_complex = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]"
    subprocess.run(
        [FFMPEG, "-y", *inputs, "-filter_complex", filter_complex, "-map", "[out]",
         "-b:a", "128k", args.out_audio],
        capture_output=True
    )

    offsets = []
    cum = 0.0
    for p in audio_paths:
        offsets.append(cum)
        cum += get_duration(p)
    print("offsets:", ", ".join(f"{os.path.basename(a)}={o:.2f}" for a, o in zip(audio_paths, offsets)))

    merged = []
    for jp, offset in zip(json_paths, offsets):
        sentences = json.load(open(jp, encoding="utf-8"))["sentences"]
        merged += shift(sentences, offset)
    for i, s in enumerate(merged, start=1):
        s["id"] = i

    json.dump({"sentences": merged, "questions": []},
              open(args.out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"wrote {len(merged)} sentences to {args.out_json}, combined audio at {args.out_audio}")


if __name__ == "__main__":
    main()
