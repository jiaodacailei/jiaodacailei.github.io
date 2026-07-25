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
   识别失败（后者是已知的短片段 ASR 局限，出现频率较低）。
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
4. **音量检测（区分"真的静音"和"识别噪声"的关键一步）**——对每条 EMPTY/
   LOW_SIMILARITY 都跑一次 `ffmpeg -af volumedetect` 拿 `max_volume`。**这一步
   不是可选的锦上添花，是本脚本最重要的判据**：真实案例（textbook-sjp-zg-l11）
   踩过的最大的坑——Whisper 在完全静音/近似静音的音频上也会"幻听"出看起来
   合理的文字（转写内容甚至能跟期望文本部分匹配），仅凭"转写出了像样的字"
   完全无法判断这段音频是不是真的有内容，反复用 word-level 转写去核实同一个
   边界会一直得到"看起来合理但其实是幻觉"的结果，只有音量检测能可靠戳穿这个
   假象。报告里会给每条 EMPTY/LOW_SIMILARITY 标注 `[疑似静音]`（`max_volume`
   明显低于该音频文件里其它条目的中位数，经验阈值是比中位数低15dB以上）还是
   `[可能是识别噪声]`（音量正常），前者几乎总是真实 bug、必须重新定位，后者
   大概率是 ASR 对短/生僻内容的正常识别局限，可以放心跳过不用继续深挖。

## 用法建议

生成完页面、本地 `http.server` 测试之前，先跑这个脚本过一遍全部数据：

    python tools/listening/verify_clips.py \
      tools/listening/work/<slug>/enriched_combined.json \
      docs/private/<slug>/audio \
      tools/listening/work/<slug>/verify_report.txt

报告分三段：EMPTY（完全没识别到内容，优先看这些，最可能是真实bug）、
LOW_SIMILARITY（读音对不上）、LEAD_SILENCE（开头疑似留白过长）。EMPTY/
LOW_SIMILARITY 每条都带 `[疑似静音]`/`[可能是识别噪声]` 标注（见上面第4条），
**优先处理带 `[疑似静音]` 标注的条目，这些几乎总是真实 bug**；`[可能是识别
噪声]` 的条目人工快速扫一眼即可，不用逐条深挖。**这个脚本只负责发现问题、
不负责自动修**——修复时同样不能只信新一轮 word-level 转写"看起来合理"，
改完之后要重新跑一遍这个脚本（或者至少对改过的条目单独跑一次 volumedetect）
确认音量真的恢复正常，不是又幻觉出了一个新的"看起来对"的错误位置。
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


def max_volume_db(clip_path):
    """跑 ffmpeg volumedetect 拿这段音频的 max_volume（dB，越接近0越响，越负
    越接近静音）。拿不到就返回 None（比如文件损坏），调用方要处理这种情况。"""
    r = subprocess.run(
        [FFMPEG, "-i", clip_path, "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True,
    )
    stderr = r.stderr.decode("utf-8", errors="replace")
    for line in stderr.splitlines():
        if "max_volume" in line:
            try:
                return float(line.split("max_volume:")[-1].replace("dB", "").strip())
            except ValueError:
                return None
    return None


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
    all_volumes = []  # (sid, max_db) for every clip that exists, to compute baseline
    total = len(sentences)

    for i, s in enumerate(sentences):
        sid = s["id"]
        clip = os.path.join(args.audio_dir, f"seg-{sid:03d}.mp3")
        if not os.path.exists(clip):
            empty.append((sid, s["text"], "文件不存在", None))
            continue

        vol = max_volume_db(clip)
        if vol is not None:
            all_volumes.append(vol)

        segs, info = model.transcribe(clip, language="ja", word_timestamps=True, vad_filter=False)
        segs = list(segs)
        words = [w for seg in segs for w in seg.words]
        recognized = "".join(w.word for w in words)

        if not recognized.strip():
            empty.append((sid, s["text"], "转写为空", vol))
            continue

        expected_reading = to_hiragana(s["text"])
        recognized_reading = to_hiragana(recognized)
        ratio = (difflib.SequenceMatcher(None, expected_reading, recognized_reading).ratio()
                 if expected_reading and recognized_reading else 0.0)
        if ratio < args.min_ratio:
            low_sim.append((sid, s["text"], recognized, round(ratio, 2), vol))

        if words and words[0].start > args.lead_warn:
            lead_silence.append((sid, s["text"], round(words[0].start, 2)))

        if (i + 1) % 20 == 0:
            print(f"...{i + 1}/{total}")

    # 中位数当"这份录音正常语音大概多响"的基准，比写死一个绝对阈值更适应
    # 不同录音场景（不同麦克风/增益/环境噪声基准差异很大）。
    baseline_db = None
    if all_volumes:
        sv = sorted(all_volumes)
        baseline_db = sv[len(sv) // 2]

    def silence_tag(vol):
        if vol is None or baseline_db is None:
            return "[音量未知]"
        return "[疑似静音]" if vol < baseline_db - 15 else "[可能是识别噪声]"

    with open(args.out_report, "w", encoding="utf-8") as f:
        f.write(f"共检查 {total} 条，EMPTY {len(empty)}，LOW_SIMILARITY {len(low_sim)}，"
                f"LEAD_SILENCE {len(lead_silence)}，音量基准(中位数) "
                f"{round(baseline_db, 1) if baseline_db is not None else '?'} dB\n\n")
        f.write("=== EMPTY（完全没识别到内容，优先核实，尤其 [疑似静音] 的）===\n")
        for sid, text, reason, vol in empty:
            f.write(f"  #{sid} {text!r}: {reason} {silence_tag(vol)}"
                    f"{' max_volume=' + str(round(vol,1)) + 'dB' if vol is not None else ''}\n")
        f.write("\n=== LOW_SIMILARITY（读音跟期望文本对不上，相似度<%.2f）===\n" % args.min_ratio)
        for sid, text, recognized, ratio, vol in sorted(low_sim, key=lambda x: x[3]):
            f.write(f"  #{sid} {text!r} 相似度={ratio}: 识别为 {recognized!r} {silence_tag(vol)}"
                    f"{' max_volume=' + str(round(vol,1)) + 'dB' if vol is not None else ''}\n")
        f.write("\n=== LEAD_SILENCE（开头疑似留白超过 %.1fs）===\n" % args.lead_warn)
        for sid, text, lead in sorted(lead_silence, key=lambda x: -x[2]):
            f.write(f"  #{sid} {text!r}: 首词起始于 {lead}s\n")

    print(f"done, wrote {args.out_report}")
    print(f"EMPTY={len(empty)} LOW_SIMILARITY={len(low_sim)} LEAD_SILENCE={len(lead_silence)}")


if __name__ == "__main__":
    main()
