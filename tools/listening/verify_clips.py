# -*- coding: utf-8 -*-
"""
用法：
  python verify_clips.py <enriched_combined.json> <audio目录> <报告输出.txt> \
      [--model medium] [--lead-warn 0.8] [--min-ratio 0.5]

共享工具（`jp-textbook-lesson`/`jp-listening-page`/`jp-meeting-listening-page`
都能用）：`build_page.py` 切完所有 `seg-NNN.mp3` 之后，**自动**把每一段重新
喂给 Whisper 转写一遍，跟 `enriched.json` 里这一句/这个词的期望文本比对，
打印一份体检报告——这是本该在人工"抽查几个位置就当作测试完成"之前就跑的
硬检查，很多真实案例里的 bug（句首被切掉一个字、前一句尾巴混进下一句开头、
生词条目前面留白过长、`refine_boundaries.py` 对齐算法在同音异字位置切偏）
都只有真的听了音频才会发现，靠人工全量抽查不现实，但让脚本转写每一条、
自动比对，几分钟就能跑完全部几百条。

## 检查项（每条数据都跑）

1. **完全没识别到内容**——转写结果是空的，通常代表这段音频要么是纯静音（切到
   了错误的位置，真实内容不在这个时间范围内），要么内容单独转写时 Whisper
   识别失败（后者是已知的短片段 ASR 局限，出现频率较低，报告里会跟"真的是
   静音"混在一起，人工确认时可以先检查 volumedetect 判断是否真的有声音，
   见 SKILL.md"常见坑"）。
2. **读音相似度过低**——把期望文本和识别文本都转成平假名（跳过标点/数字），
   用 `difflib.SequenceMatcher` 算相似度，低于 `--min-ratio`（默认0.5）就
   打印警告。按读音比不按字面比，因为"銭湯被听成戦闘"这类同音异字是正常
   识别噪声，不代表真的错位；但如果读音都差得远，大概率是真的内容错位或者
   切到了别的句子。
3. **疑似开头留白过长**——`word_timestamps=True` 拿到这段音频内部识别到的
   第一个词的起始时间，如果超过 `--lead-warn`（默认0.8秒），可能是边界切
   早了、前面留了太多空白（真实案例：生词"見込み"最初切出来的音频前面有
   几秒纯静音才开始说话）。**不是所有偏晚都代表 bug**——有些词本身音频里就
   有正常的呼吸/停顿，报告只是提醒复核，不是直接判定为错误。

## 用法建议

生成完页面、本地 `http.server` 测试之前，先跑这个脚本过一遍全部数据：

    python tools/listening/verify_clips.py \
      tools/listening/work/<slug>/enriched_combined.json \
      docs/private/<slug>/audio \
      tools/listening/work/<slug>/verify_report.txt

报告分三段：EMPTY（完全没识别到内容，优先看这些，最可能是真实bug）、
LOW_SIMILARITY（读音对不上）、LEAD_SILENCE（开头疑似留白过长）。**这个脚本
只负责发现问题、不负责自动修**——每一条列出来的疑点都需要人工判断是不是真的
问题（可能是识别噪声），不要看到报告有几十条警告就慌，但也不要因为报告"太长"
就跳过不看，尤其 EMPTY 和严重的 LOW_SIMILARITY（比如相似度 <0.2）几乎总是
真实问题。
"""
import sys
import os
import re
import json
import argparse
import difflib
import imageio_ffmpeg
import subprocess
import pykakasi

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_kks = pykakasi.kakasi()
_PUNCT_RE = re.compile(r"[\s　、。，,．.!?！？「」『』()（）:：;；~〜・…\-—―'\"０-９0-9]")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def to_hiragana(text):
    text = _PUNCT_RE.sub("", text or "")
    return "".join(t["hira"] for t in _kks.convert(text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("enriched_json")
    ap.add_argument("audio_dir")
    ap.add_argument("out_report")
    ap.add_argument("--model", default="medium")
    ap.add_argument("--lead-warn", type=float, default=0.8)
    ap.add_argument("--min-ratio", type=float, default=0.5)
    args = ap.parse_args()

    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8")

    data = json.load(open(args.enriched_json, encoding="utf-8"))
    sentences = sorted(data["sentences"], key=lambda s: s["id"])

    empty, low_sim, lead_silence = [], [], []
    total = len(sentences)

    for i, s in enumerate(sentences):
        sid = s["id"]
        clip = os.path.join(args.audio_dir, f"seg-{sid:03d}.mp3")
        if not os.path.exists(clip):
            empty.append((sid, s["text"], "文件不存在"))
            continue

        segs, info = model.transcribe(clip, language="ja", word_timestamps=True, vad_filter=False)
        segs = list(segs)
        words = [w for seg in segs for w in seg.words]
        recognized = "".join(w.word for w in words)

        if not recognized.strip():
            empty.append((sid, s["text"], "转写为空"))
            continue

        expected_reading = to_hiragana(s["text"])
        recognized_reading = to_hiragana(recognized)
        ratio = (difflib.SequenceMatcher(None, expected_reading, recognized_reading).ratio()
                 if expected_reading and recognized_reading else 0.0)
        if ratio < args.min_ratio:
            low_sim.append((sid, s["text"], recognized, round(ratio, 2)))

        if words and words[0].start > args.lead_warn:
            lead_silence.append((sid, s["text"], round(words[0].start, 2)))

        if (i + 1) % 20 == 0:
            print(f"...{i + 1}/{total}")

    with open(args.out_report, "w", encoding="utf-8") as f:
        f.write(f"共检查 {total} 条，EMPTY {len(empty)}，LOW_SIMILARITY {len(low_sim)}，"
                f"LEAD_SILENCE {len(lead_silence)}\n\n")
        f.write("=== EMPTY（完全没识别到内容，优先核实）===\n")
        for sid, text, reason in empty:
            f.write(f"  #{sid} {text!r}: {reason}\n")
        f.write("\n=== LOW_SIMILARITY（读音跟期望文本对不上，相似度<%.2f）===\n" % args.min_ratio)
        for sid, text, recognized, ratio in sorted(low_sim, key=lambda x: x[3]):
            f.write(f"  #{sid} {text!r} 相似度={ratio}: 识别为 {recognized!r}\n")
        f.write("\n=== LEAD_SILENCE（开头疑似留白超过 %.1fs）===\n" % args.lead_warn)
        for sid, text, lead in sorted(lead_silence, key=lambda x: -x[2]):
            f.write(f"  #{sid} {text!r}: 首词起始于 {lead}s\n")

    print(f"done, wrote {args.out_report}")
    print(f"EMPTY={len(empty)} LOW_SIMILARITY={len(low_sim)} LEAD_SILENCE={len(lead_silence)}")


if __name__ == "__main__":
    main()
