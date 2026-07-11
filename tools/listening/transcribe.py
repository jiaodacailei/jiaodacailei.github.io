# -*- coding: utf-8 -*-
"""
用法：python transcribe.py <音频文件> <输出transcript.json> [--model medium]

按固定时长切块喂给 faster-whisper 转写（绕开 VAD 在长静音/嘈杂片段里
整段吞掉或产生幻觉的问题），输出带时间戳的日语文本片段列表。

转写质量取决于录音本身的清晰度，结果通常需要人工复听筛选（保留听得懂的
句子，丢掉明显跑偏/幻觉的部分），再交给 add_furigana.py 处理。
"""
import sys
import os
import json
import time
import subprocess
import argparse
from faster_whisper import WhisperModel
import imageio_ffmpeg

# Windows 控制台默认用 cp932/gbk 之类的窄编码，print 日语/中文文本时容易
# UnicodeEncodeError 崩溃（哪怕转写本身已经成功、结果已经写盘）。强制 stdout/stderr
# 用 UTF-8，编不了的字符替换掉而不是直接抛异常。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def get_duration(audio_path):
    probe = subprocess.run(
        [FFMPEG, "-i", audio_path],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    dur_line = [l for l in probe.stderr.splitlines() if "Duration" in l][0]
    hms = dur_line.split("Duration:")[1].split(",")[0].strip()
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("out_json")
    ap.add_argument("--model", default="medium", help="whisper 模型: small/medium/large-v3")
    ap.add_argument("--chunk-sec", type=int, default=25)
    args = ap.parse_args()

    total_dur = get_duration(args.audio)
    print(f"Total duration: {total_dur:.1f}s", flush=True)

    t0 = time.time()
    print(f"Loading model {args.model}...", flush=True)
    model = WhisperModel(args.model, device="cpu", compute_type="int8")

    work_dir = os.path.join(os.path.dirname(os.path.abspath(args.out_json)), "chunks_tmp")
    os.makedirs(work_dir, exist_ok=True)

    all_segments = []
    offset = 0.0
    idx = 0
    while offset < total_dur:
        chunk_path = os.path.join(work_dir, f"chunk_{idx:04d}.wav")
        subprocess.run(
            [FFMPEG, "-y", "-ss", str(offset), "-t", str(args.chunk_sec), "-i", args.audio,
             "-ar", "16000", "-ac", "1", chunk_path],
            capture_output=True
        )
        segments, info = model.transcribe(
            chunk_path,
            language="ja",
            beam_size=5,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            all_segments.append({
                "start": round(offset + seg.start, 2),
                "end": round(offset + seg.end, 2),
                "text": text,
            })
            print(f"[{offset+seg.start:7.2f} - {offset+seg.end:7.2f}] {text}", flush=True)
        os.remove(chunk_path)
        offset += args.chunk_sec
        idx += 1
    os.rmdir(work_dir)

    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump({"language": "ja", "duration": total_dur, "segments": all_segments}, f, ensure_ascii=False, indent=2)

    print(f"Done in {time.time()-t0:.1f}s. {len(all_segments)} segments written to {args.out_json}", flush=True)
    print("下一步：人工复听 transcript，删掉明显跑偏/幻觉的段落，只留听得懂的句子，再跑 add_furigana.py", flush=True)


if __name__ == "__main__":
    main()
