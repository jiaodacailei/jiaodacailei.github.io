# -*- coding: utf-8 -*-
"""
用法：
  python check_clip_drift.py <enriched_combined.json> <docs/private/<slug>> [--tolerance 0.15]

共享工具（`jp-textbook-lesson` 用）：批量比较 `docs/private/<slug>/audio/
seg-NNN.mp3` 磁盘上的实际时长，跟 `enriched_combined.json` 里 `end-start`
算出来的期望时长，报告对不上的 id——**对不上就说明这个文件在 `build_page.py`
生成之后被别的操作（最常见是 `trim_clip_silence.py`）动过**，值得重点复核
内容有没有被裁掉。

真实案例（textbook-sjp-zg-l14）：用户反馈"採用試験"这一个生词边界不准，
排查时先入为主假设是 `enriched.json` 里的边界本身算错了，套用 RMS/word-
level 那一套分析了很久都对不上——直到顺手用 `faster_whisper` 转写时印出
`info.duration`，才发现磁盘文件的实际时长（1.07秒）跟 `enriched_combined.
json` 里这个词条的期望时长（1.76秒）根本不一致，说明要找的根本不是"边界
算错"，是"文件后来被 `trim_clip_silence.py` 裁过、而且裁过头了"——两类
问题排查方向完全不同，不先做这一步比较、直接套用边界分析会在错误的坐标
系里绕远路。用这个脚本把这一步固定成一条命令，不用每次现写。

对全部生词表跑一遍这个脚本、看有多少条 drift，只是**筛出"可能被动过、
值得复核"的候选名单**，不代表 drift 本身就是bug——`trim_clip_silence.py`
正常工作时（裁掉真实存在的多余静音、没伤到内容）也会产生 drift，这是
预期行为。drift 名单出来之后还要配合批量转写（听写结果明显不像这个词才
是真正的嫌疑对象）+ 带足够前后文的 word-level 转写交叉核实（孤立单条
clip 转写本身不可靠，"转写不对"不能直接当成"内容被裁坏"的证据），才能
定论，不能只看这个脚本的输出就动手改。
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


def get_duration(path):
    r = subprocess.run([FFMPEG, "-i", path], capture_output=True)
    m = re.search(rb"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
    if not m:
        return None
    h, mi, se = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(se)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("enriched_combined_json")
    ap.add_argument("slug_dir", help="docs/private/<slug>（脚本会在它下面找 audio/ 子目录）")
    ap.add_argument("--tolerance", type=float, default=0.15,
                     help="时长差异超过这个秒数才报告，默认0.15秒（正常的裁剪缓冲/舍入误差不算）")
    args = ap.parse_args()

    data = json.load(open(args.enriched_combined_json, encoding="utf-8"))
    audio_dir = os.path.join(args.slug_dir, "audio")

    drifted, missing = [], []
    for s in sorted(data["sentences"], key=lambda s: s["id"]):
        expected = s["end"] - s["start"]
        path = os.path.join(audio_dir, f"seg-{s['id']:03d}.mp3")
        if not os.path.exists(path):
            missing.append(s["id"])
            continue
        actual = get_duration(path)
        if actual is None:
            missing.append(s["id"])
            continue
        diff = actual - expected
        if abs(diff) > args.tolerance:
            drifted.append((s["id"], s["text"][:20], expected, actual, diff))

    print(f"共 {len(data['sentences'])} 条，{len(drifted)} 条时长对不上（可能被后续操作动过，"
          f"需要配合批量转写+带上下文交叉核实，不代表一定是bug）：")
    for sid, text, expected, actual, diff in drifted:
        print(f"  id={sid} {text!r} expected={expected:.2f} actual={actual:.2f} diff={diff:+.2f}")
    if missing:
        print(f"\n{len(missing)} 条文件缺失或读取失败: {missing}")


if __name__ == "__main__":
    main()
