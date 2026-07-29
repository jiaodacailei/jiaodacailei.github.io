# -*- coding: utf-8 -*-
"""
用法：python trim_clip_silence.py <audio目录> [--noise -35dB] [--pad 0.12] [--min-dur 0.4] [--dry-run]

共享工具（`jp-textbook-lesson` 生词条目专用，会话/课文不要用——那两类句子
的 `t`/`char_times` 是相对句子自己 start 算出来的绝对坐标系，裁剪音频文件
但不同步调整这些时间戳会导致跟读高亮全错位；生词条目没有 `char_times`，
播放只认音频文件本身，裁剪完全安全）。

## 背景（真实踩过的坑）

`build_page.py --data-driven` 切生词音频时，起止边界为了"宁可留一截静音
也不敢切掉真实内容"，天然会留出比较宽的缓冲——单看某一条不算错（内容没
被切掉），但整批下来大量生词条目前后加起来能有 3~8 秒静音，实际语音只占
一两秒。真实案例（textbook-sjp-zg-l12）：90 条生词平均单条时长 4.73 秒，
中位数每字符 1.6~2 秒（正常语速这个字符数 0.2~0.4 秒/字符就够了），用户
反馈"大部分单词发音前后都有很多空白，上一课也这样，没有优化到脚本里
吗"——这是真实存在、每一课都会复现的问题，得在工具链里修一次，不能每课
都指望人工一条条抠。

## 做法

对每个已经切好的生词音频文件（`build_page.py` 生成的 `seg-XXX.mp3`），用
`ffmpeg silencedetect` 探测这段音频里的静音区间，反推出"真正有声音"的
起止范围，按这个范围重新裁剪（前后各留 `--pad` 秒缓冲，不裁得太死），
直接覆盖原文件。**只安全用于没有 `char_times`/`t` 时间戳依赖的音频**（生词
条目——`build_page.py` 的 `sentence_to_data()` 对没有 `char_times` 的句子
直接用 `kana` 字段渲染，不会有任何数据引用音频文件内部的绝对时间点，
裁剪音频文件、不动 `data.js` 完全安全）。

跑完之后建议至少抽查几条确认没有裁过头（真的把开头/结尾的字裁掉了）——
`--noise`/`--pad` 是启发式参数，遇到气声很轻的词条掐音量阈值可能不够
灵敏，宁可留多一点缓冲也不要冒进调低阈值。
"""
import sys
import os
import re
import glob
import argparse
import subprocess
import imageio_ffmpeg

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

_SILENCE_START_RE = re.compile(r"silence_start:\s*([\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([\d.]+)")


def get_duration(path):
    r = subprocess.run([FFMPEG, "-i", path], capture_output=True)
    m = re.search(rb"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
    if not m:
        return None
    h, mi, se = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(se)


def detect_speech_range(path, noise_db, min_silence=0.08):
    """返回 (speech_start, speech_end)，取不到就返回 None（整段可能全是
    静音/太短探测不出来，调用方应该跳过不裁，保留原样）。"""
    duration = get_duration(path)
    if duration is None:
        return None
    r = subprocess.run(
        [FFMPEG, "-i", path, "-af",
         f"silencedetect=noise={noise_db}:d={min_silence}", "-f", "null", "-"],
        capture_output=True,
    )
    text = r.stderr.decode("utf-8", errors="replace")
    starts = [float(x) for x in _SILENCE_START_RE.findall(text)]
    ends = [float(x) for x in _SILENCE_END_RE.findall(text)]
    # silence_end 有时会因为文件读到结尾没有对应输出，跟 starts 数量对不上，
    # 按能配对的部分处理，落单的 start（一路静音到文件结尾）按 duration 收尾。
    silences = []
    for i, st in enumerate(starts):
        en = ends[i] if i < len(ends) else duration
        silences.append((st, en))

    if not silences:
        # 整段没检测到任何静音——说明从头到尾都是"有声音"（或者噪声阈值
        # 不够灵敏），不裁，原样保留最安全。
        return None

    speech_start = 0.0
    if silences[0][0] <= 0.05:
        speech_start = silences[0][1]
    speech_end = duration
    if silences[-1][1] >= duration - 0.05:
        speech_end = silences[-1][0]

    if speech_end <= speech_start:
        return None
    return speech_start, speech_end


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio_dir")
    ap.add_argument("--noise", default="-35dB")
    ap.add_argument("--pad", type=float, default=0.12)
    ap.add_argument("--min-dur", type=float, default=0.4,
                     help="裁剪后如果比这个还短，判定探测大概率出错，跳过不裁")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.audio_dir, "*.mp3")))
    print(f"{len(files)} files in {args.audio_dir}")

    trimmed, skipped = 0, 0
    for path in files:
        duration = get_duration(path)
        rng = detect_speech_range(path, args.noise)
        if rng is None:
            skipped += 1
            continue
        speech_start, speech_end = rng
        new_start = max(0.0, speech_start - args.pad)
        new_end = min(duration, speech_end + args.pad)
        new_dur = new_end - new_start
        if new_dur < args.min_dur or new_dur >= duration - 0.02:
            skipped += 1
            continue

        print(f"  {os.path.basename(path)}: {duration:.2f}s -> "
              f"[{new_start:.2f},{new_end:.2f}] ({new_dur:.2f}s)")
        trimmed += 1
        if args.dry_run:
            continue
        tmp_path = path + ".trimmed.mp3"
        subprocess.run(
            [FFMPEG, "-y", "-ss", str(new_start), "-t", str(new_dur),
             "-i", path, "-acodec", "copy", tmp_path],
            capture_output=True,
        )
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            os.replace(tmp_path, path)
        else:
            print(f"    WARNING: trim produced empty/missing file, kept original")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    print(f"\ntrimmed {trimmed}, skipped {skipped} (dry_run={args.dry_run})")


if __name__ == "__main__":
    main()
