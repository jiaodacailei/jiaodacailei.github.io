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
4. **音量检测**——对每条 EMPTY/LOW_SIMILARITY 都跑一次 `ffmpeg -af volumedetect`
   拿 `max_volume`，报告里标注 `[疑似静音]`（明显低于该音频文件里其它条目的
   中位数，经验阈值是比中位数低15dB以上）还是 `[可能是识别噪声]`（音量正常）。
   **这一步只能分辨"这段时间范围里有没有声音"，分辨不出"这段声音是不是正确的
   内容"**——见下面第5条，光凭这一项做取舍是不够的，`[可能是识别噪声]` **不等于
   "可以跳过不用管"**。
5. **内容合理性判据（区分"真的没内容"和"内容混进来了但不是这一条该有的"）**——
   真实案例（textbook-sjp-zg-l11）：生词"〜ら"/"抜く"/"さっと"三条最初都被
   本脚本正确标记为 LOW_SIMILARITY，但音量检测给它们打了 `[可能是识别噪声]`
   （因为这三条切出来的音频里确实有一截响亮的真实语音，只是内容是从旁边混
   进来的——不是纯静音，音量检测在这种情况下完全帮不上忙），当时误判为"大概
   率是正常识别局限"跳过了，用户实际听后发现全部是真 bug（错位/截断/内容
   对不上）。事后核对发现一个更有效的信号：**识别出来的文字本身像不像连贯
   真实的日语**——"はっ!"「ご視聴ありがとうございました」「どう?」都是完整、
   通顺的日语词/短语，说明 Whisper 真的听到了某处的真实人声，只是不是这一条
   该有的内容（边界切错了位置，混进了旁边的音频）；反过来像"TNM"「SIM」
   「C」这种夹杂拉丁字母/数字的乱码输出，通常代表 Whisper 在真的很短/生僻的
   孤立词上转写失败，位置本身没问题，这才是可以放心跳过的"识别噪声"。报告
   会在每条 LOW_SIMILARITY 后面追加 `[命中已知静音幻觉套话]`（识别文本命中
   "ご視聴ありがとうございました"这类 Whisper 对静音的经典幻觉输出，几乎
   100%是 bug）/`[疑似内容错位-像连贯日语]`（识别文本大部分是假名/汉字且够
   长，像正常日语而不是识别乱码，**必须人工复核，不能因为音量正常就跳过**）
   /`[像ASR对短词的识别局限]`（识别文本主要是拉丁字母/数字乱码）。**这一项
   判据独立于音量检测，两项都要看，不能只看音量**。
   **`[像ASR对短词的识别局限]` 不是"safe to skip"的信号，只是"这条没有更
   强的信号"**——真实案例（textbook-sjp-zg-l11）：生词"将棋"（识别为"ん"）
   和"碁"（识别为"5"）都带着这个标注、音量也正常，一度被当成"大概率没问题"
   放过，用户实际听后发现两条都是真 bug（"将棋"边界整个落在两词之间的静音
   段，"碁"前面留了2.27秒空白）。**乱码输出（"ん"/"5"/"TNM"这类）本身不
   携带任何关于位置对不对的信息——它既可能出现在"位置正确、但词本身太短/
   太生僻 ASR 处理不好"的场景（比如之前验证过的"定年"，VAD 修好边界后仍然
   识别不准但位置是对的），也可能出现在"位置错了、只是残留的噪声/静音刚好
   让 Whisper 吐出乱码而不是幻觉出完整词"的场景（这次的"将棋"/"碁"）——
   两种场景从识别文本本身完全无法区分**。**唯一可靠的做法**：所有
   LOW_SIMILARITY 条目，尤其是1~2个假名的短生词（这类词 ASR 天然不可靠，
   恰好又是最容易被"乱码=正常识别局限"这个错误直觉放过的一类），只要没有
   独立证据支持"位置是对的"（比如：识别文本虽然乱但至少读音片段能对上，或者
   已经用逐帧振幅剖面/宽窗口转写核实过），就不能仅凭"音量正常+识别文本是
   乱码"两项标注为绿灯而跳过——按上一条"人工审核环节不能省"的结论，这类
   条目最终还是要靠逐帧 RMS 振幅剖面（`wave`模块按50ms窗口算能量，参考
   本文件所在 skill 的 SKILL.md"常见坑"一节里的具体做法）人工确认真实内容
   边界，不能停留在"报告没有标红"就当作验证完成。

## 用法建议

生成完页面、本地 `http.server` 测试之前，先跑这个脚本过一遍全部数据：

    python tools/listening/verify_clips.py \
      tools/listening/work/<slug>/enriched_combined.json \
      docs/private/<slug>/audio \
      tools/listening/work/<slug>/verify_report.txt

报告分三段：EMPTY（完全没识别到内容，优先看这些，最可能是真实bug）、
LOW_SIMILARITY（读音对不上）、LEAD_SILENCE（开头疑似留白过长）。EMPTY/
LOW_SIMILARITY 每条都带音量标注（`[疑似静音]`/`[可能是识别噪声]`，见上面
第4条）和内容合理性标注（`[命中已知静音幻觉套话]`/`[疑似内容错位-像连贯
日语]`/`[像ASR对短词的识别局限]`，见上面第5条）。**这两项标注只用来排优先
级，不能用来判定"可以不管"**：`[疑似静音]`/`[命中已知静音幻觉套话]`/
`[疑似内容错位-像连贯日语]` 三者任意命中一个，几乎总是真 bug，优先处理；
但 `[像ASR对短词的识别局限]`（识别文本是乱码）**不是"没问题"的信号，只是
"这条没有更强的信号"**——乱码输出本身无法区分"位置对、词太短ASR处理不好"
和"位置错、残留噪声让 Whisper 吐出乱码"，历史上两种情况都真实出现过（见
上面第5条"将棋/碁"的案例）。**实际结论**：EMPTY 和全部 LOW_SIMILARITY
条目（不分标注）都需要人工过一遍，标注只决定"先看哪个、后看哪个"，不
决定"要不要看"——尤其是1~2个假名的短生词，这类词天然是 ASR 最不可靠、
也最容易被"乱码=正常识别局限"这个错误直觉放过的一类，怀疑边界不对时用
逐帧 RMS 振幅剖面（`wave`模块按50ms窗口算能量，不依赖任何转写/VAD模型，
参考 SKILL.md"常见坑"一节的具体做法）或宽窗口 word-level/VAD 转写+`ffmpeg
silencedetect`重新定位真实边界。**这个脚本只负责发现问题、缩小复核范围，
不负责自动判定"没问题"、也不负责自动修**——修复时同样不能只信新一轮
word-level 转写"看起来合理"，改完之后要重新跑一遍这个脚本确认两项标注都
恢复正常，不是又混进了一个新的"看起来对但其实是别处内容"的错误位置。
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

# Whisper 对着静音/近似静音音频常"幻听"出的几句经典套话（YouTube 视频片尾语的
# 训练数据痕迹），命中即高置信度判定为静音位置写错了 bug，不是识别噪声。
# 不是穷举列表，遇到新的幻觉套话就往这里加。
HALLUCINATION_PHRASES = [
    "ご視聴ありがとうございました",
    "字幕視聴ありがとうございました",
    "最後までご視聴いただきありがとうございました",
    "チャンネル登録よろしくお願いします",
    "本当にありがとうございます",
]


def to_hiragana(text):
    text = _PUNCT_RE.sub("", text or "")
    return "".join(t["hira"] for t in _kks.convert(text))


def _is_ja_char(c):
    o = ord(c)
    return (0x3040 <= o <= 0x30FF) or (0x4E00 <= o <= 0x9FFF) or (0x3400 <= o <= 0x4DBF)


def content_risk_tag(recognized):
    """光看音量分不清"这里有没有声音"和"这段声音是不是该在这的内容"——一段
    音频可能混进了旁边词/旁白的真实人声，音量完全正常，但内容是错的。这里换
    一个跟音量无关的判据：识别出来的文字本身像不像连贯真实的日语。像的话，说明
    Whisper 真的听到了某处的人声（只是不是这条该有的），必须人工复核；只是
    拉丁字母/数字乱码的话，大概率是 Whisper 在孤立短词上的正常识别局限。"""
    stripped = recognized.strip()
    if not stripped:
        return ""
    if any(p in stripped for p in HALLUCINATION_PHRASES):
        return "[命中已知静音幻觉套话]"
    ja_chars = [c for c in stripped if not c.isspace()]
    ja_ratio = (sum(1 for c in ja_chars if _is_ja_char(c)) / len(ja_chars)) if ja_chars else 0.0
    if ja_ratio >= 0.8 and len(ja_chars) >= 2:
        return "[疑似内容错位-像连贯日语]"
    return "[像ASR对短词的识别局限]"


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
            f.write(f"  #{sid} {text!r} 相似度={ratio}: 识别为 {recognized!r} "
                    f"{silence_tag(vol)}{content_risk_tag(recognized)}"
                    f"{' max_volume=' + str(round(vol,1)) + 'dB' if vol is not None else ''}\n")
        f.write("\n=== LEAD_SILENCE（开头疑似留白超过 %.1fs）===\n" % args.lead_warn)
        for sid, text, lead in sorted(lead_silence, key=lambda x: -x[2]):
            f.write(f"  #{sid} {text!r}: 首词起始于 {lead}s\n")

    print(f"done, wrote {args.out_report}")
    print(f"EMPTY={len(empty)} LOW_SIMILARITY={len(low_sim)} LEAD_SILENCE={len(lead_silence)}")


if __name__ == "__main__":
    main()
