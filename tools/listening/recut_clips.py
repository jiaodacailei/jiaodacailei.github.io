# -*- coding: utf-8 -*-
"""
用法：
  python recut_clips.py <combined音频> <enriched_combined.json> <docs/private/<slug>> <id1> [<id2> ...]

共享工具（`jp-textbook-lesson` 用）：只重新切某几个 `id` 对应的 `seg-NNN.mp3`，
不碰其它任何文件——改完个别句子的边界（不管是手工 patch 还是
`apply_manual_overrides.py`）之后配套用，避免为了改一两句边界重新跑一遍
整个 `build_page.py`（那样连没改过的生词裁剪结果都会被静默撤销，见
SKILL.md"常见坑"）。

**必须传 `combined音频`（`merge_sections.py` 拼接出来的那一份，`build_page.py`
生成页面时实际用来切 `audio/` 目录的同一份文件），不要传某一段自己的原始
音频**——`enriched_combined.json` 里的 `start`/`end` 是合并后的绝对时间，
直接对着合并前的单段原始音频（本地坐标系）用会切到完全无关的位置。真实
案例（textbook-sjp-zg-l14）：手工改边界时来回在"这一段自己的原始音频，
本地坐标系"和"合并后的音频，绝对坐标系"之间切换，一次算错直接把另一个
句子的音频文件覆盖了（把只该属于会话的 `seg-018.mp3` 用课文的偏移量重新
切了一遍）——本脚本固定只吃 `combined` 音频 + `enriched_combined.json`，
`id` 直接对应 `audio/seg-{id:03d}.mp3`，不用调用方自己换算"这一段的本地
时间戳+这一段在合并音频里的偏移量"，从根上消除这类算错偏移量的风险。

切完不会自动更新 `data.js` 里的 `tokens`（跟读高亮时间戳）——那是
`patch_sentence_tokens.py` 的职责，两个工具分开跑，因为文本层面（tokens）
的更新只需要 `enriched_combined.json` 里已经算好的 `char_times`，跟音频
文件本身是否已经重新切好没有先后依赖关系。
"""
import sys
import os
import subprocess
import argparse
import json
import imageio_ffmpeg

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("combined_audio")
    ap.add_argument("enriched_combined_json")
    ap.add_argument("out_dir", help="docs/private/<slug>（脚本会在它下面找/建 audio/ 子目录）")
    ap.add_argument("ids", nargs="+", type=int)
    ap.add_argument("--bitrate", default="128k")
    args = ap.parse_args()

    data = json.load(open(args.enriched_combined_json, encoding="utf-8"))
    by_id = {s["id"]: s for s in data["sentences"]}

    missing = [i for i in args.ids if i not in by_id]
    if missing:
        print(f"FAIL: enriched_combined.json 里找不到这些 id: {missing}")
        sys.exit(1)

    audio_dir = os.path.join(args.out_dir, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    for i in args.ids:
        s = by_id[i]
        out_path = os.path.join(audio_dir, f"seg-{i:03d}.mp3")
        subprocess.run(
            [FFMPEG, "-y", "-ss", str(s["start"]), "-t", str(s["end"] - s["start"]),
             "-i", args.combined_audio, "-b:a", args.bitrate, out_path],
            capture_output=True
        )
        print(f"re-cut seg-{i:03d}.mp3 [{s['start']},{s['end']}] text={s['text'][:20]!r}")


if __name__ == "__main__":
    main()
