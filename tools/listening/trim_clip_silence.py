# -*- coding: utf-8 -*-
"""
用法：python trim_clip_silence.py <audio目录> [--rel-db 20] [--pad 0.12] [--min-dur 0.35] [--gap 0.2] [--dry-run]

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

## 第一版用 `ffmpeg silencedetect` 固定阈值踩的坑

最初版本用 `silencedetect=noise=-35dB` 这种**绝对**阈值判定静音。真实案例
（textbook-sjp-zg-l12，"不足する"这条）：这份录音里"不足する"这条真实语音
前后的背景底噪本身就有 -35~-45dB（比常见的干净静音 -50dB 以下更"响"，
可能是录音环境/压缩本身的问题），固定阈值 -35dB 判不出这段底噪是"静音"，
裁剪完这条还是留了将近5秒（人工用逐帧 RMS 剖面核实，真实语音只占大约
1.3秒）。**同一个绝对阈值没法适应不同录音/不同片段的底噪基准**，必须
按每条 clip 自己的响度动态定。

## 现在的做法：按每条 clip 自己的响度算相对阈值，找最响的连续区间

对每个已经切好的生词音频文件（`build_page.py` 生成的 `seg-XXX.mp3`）：
1. 读裸 PCM（`wave` 模块），按 `--frame-ms`（默认30ms）切帧算 RMS 转 dB。
2. 阈值 = 这条 clip 自己的峰值 dB − `--rel-db`（默认20dB）——不用固定绝对
   阈值，每条 clip 各自的"响"和"静音"都是相对自己的峰值判断，能适应不同
   底噪基准的录音。
3. 找到所有"响度 ≥ 阈值"的帧，合并成连续区间——允许 `--gap` 秒（默认
   0.2秒）以内的短暂降到阈值以下（辅音收尾/促音这类正常语音内部的短暂
   静默，不能真的断开），超过这个间隔才算两段不同的区间。
4. 取时长最长的一段连续区间当作"真实语音"——生词条目正常应该只有一段
   连续语音，如果探测出多段合理长度接近的区间，八成是相邻词的音频粘连
   进来了，只留最长的一段更安全（宁可保守漏一点，也不要错留邻居的音频）。
5. 前后各留 `--pad` 秒缓冲，裁剪覆盖原文件。

跑完之后建议至少抽查几条确认没有裁过头（真的把开头/结尾的字裁掉了），
更重要的是**跑完一定要重新过一遍 `verify_clips.py`**——这是启发式参数，
不可能对所有词条都完美，裁完不代表就不用检查了。
"""
import sys
import os
import re
import glob
import math
import wave
import argparse
import subprocess
import numpy as np
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


def rms_profile(path, frame_ms):
    """返回 (frame_start_times, frame_db_list, duration)。"""
    wav_path = path + ".rms_tmp.wav"
    subprocess.run([FFMPEG, "-y", "-i", path, "-ar", "16000", "-ac", "1", wav_path],
                    capture_output=True)
    try:
        with wave.open(wav_path, "rb") as w:
            n = w.getnframes()
            sr = w.getframerate()
            raw = w.readframes(n)
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    frame_len = max(1, int(sr * frame_ms / 1000))
    times, dbs = [], []
    for i in range(0, len(samples) - frame_len, frame_len):
        chunk = samples[i:i + frame_len]
        rms = math.sqrt(np.mean(chunk ** 2)) if len(chunk) else 0
        db = 20 * math.log10(rms / 32768.0) if rms > 0 else -99.0
        times.append(i / sr)
        dbs.append(db)
    duration = len(samples) / sr if sr else 0
    return times, dbs, duration


def detect_speech_range(path, rel_db, gap, frame_ms):
    """按 clip 自己的峰值算相对阈值，找最长的连续"响"区间，返回
    (speech_start, speech_end)，找不到（比如整段都很平/太短）返回 None。"""
    times, dbs, duration = rms_profile(path, frame_ms)
    if not dbs or duration <= 0:
        return None
    peak = max(dbs)
    threshold = peak - rel_db
    loud = [d >= threshold for d in dbs]

    # 合并连续（允许 gap 秒以内的短暂降到阈值以下）的"响"帧成区间。
    frame_sec = frame_ms / 1000.0
    gap_frames = max(1, int(round(gap / frame_sec)))
    regions = []
    i = 0
    n = len(loud)
    while i < n:
        if not loud[i]:
            i += 1
            continue
        start_i = i
        end_i = i
        j = i + 1
        while j < n:
            if loud[j]:
                end_i = j
                j += 1
            elif j - end_i <= gap_frames:
                j += 1
            else:
                break
        regions.append((times[start_i], times[end_i] + frame_sec))
        i = j

    if not regions:
        return None
    # 取最长的一段——生词条目正常只有一段连续语音，多段的话最长的那段
    # 最可能是真实内容，短的大概率是粘连/噪声毛刺。
    speech_start, speech_end = max(regions, key=lambda r: r[1] - r[0])
    if speech_end <= speech_start:
        return None
    return speech_start, speech_end


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio_dir")
    ap.add_argument("--rel-db", type=float, default=20.0,
                     help="阈值=这条clip峰值dB减这个数，越大越宽松（保留更多）")
    ap.add_argument("--gap", type=float, default=0.2,
                     help="允许连续区间内部短暂降到阈值以下多少秒，不算断开")
    ap.add_argument("--frame-ms", type=float, default=30.0)
    ap.add_argument("--pad", type=float, default=0.15)
    ap.add_argument("--min-dur", type=float, default=0.35,
                     help="裁剪后如果比这个还短，判定探测大概率出错，跳过不裁")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.audio_dir, "*.mp3")))
    print(f"{len(files)} files in {args.audio_dir}")

    trimmed, skipped = 0, 0
    for path in files:
        rng = detect_speech_range(path, args.rel_db, args.gap, args.frame_ms)
        if rng is None:
            skipped += 1
            continue
        speech_start, speech_end = rng
        duration = get_duration(path)
        if duration is None:
            skipped += 1
            continue

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
