# -*- coding: utf-8 -*-
"""
用法：
  python audit_boundaries_quietpoint.py <enriched.json> <这段原始音频>
      [--rel-frame-ms 5] [--search-back 0.35] [--search-front 0.03]
      [--rise-threshold 6] [--loud-threshold -40] [--margin 0.02]
      [--fix] [--report report.txt]

共享工具（`jp-textbook-lesson`/`jp-listening-page`/`jp-meeting-listening-page`
都能用）：对 `enriched.json` 里每一个内部边界（相邻两句/两词之间的分界点，
不管中间原本有没有明显停顿），检测这个边界是不是设晚了、把下一句/下一词
的开头一截音吞进了上一句/上一词的尾部。

## 为什么需要这个工具（跟 `audit_boundaries_rms.py` 的关系）

`audit_boundaries_rms.py` 用"burst 检测"判断边界是否落在一段连续语音内部，
命中之后要求人工用 word-level 转写交叉核实。**这个工具是那一步排查方法
本身的教训沉淀**——真实案例（textbook-sjp-zg-l15）：反复发现 word-level
转写（不管窄窗口还是宽窗口）的时间戳本身就不可靠，用它验证"这个边界
到底晚不晚"，得出的结论有相当比例是错的（该改的边界被判定"安全"而放过、
不该改的边界被误判成"两个不同的词/句子各自的起振"）。

这个工具换一个思路：不依赖任何转写文本，纯粹用能量剖面自己回答问题——
"这个边界之前一小段时间内，音频真正安静下来过没有，安静到什么时候"，
拿这个"真正的安静点"直接跟边界本身的响度比较。**这个判据不需要猜"这是
哪个字"，只需要测"这里响不响"，物理测量比语言模型的时间戳猜测更可靠**。

## 核心算法

对每个边界 B（下一句/下一词的 `start`，通常等于上一句/上一词的 `end`）：
1. 在 [B-search_back, B-search_front] 这段范围内找响度最低点（`quiet_min`）
   ——这段范围如果真的有自然停顿，最低点会落在停顿正中间；如果两句/两词
   紧挨着读、中间本来就没有真正的静音，最低点也会是"相对没那么响"的位置，
   两种情况这一步都能正常工作。
2. 比较边界 B 处的响度（`at_B`）跟 `quiet_min` 的响度差（`rise`）。
3. `rise` 超过阈值、且 `at_B` 本身已经是"响"的水平（不是两边都很安静的
   正常波动）→ 标记为可疑：边界很可能设晚了，下一句/下一词的开头一截被
   划给了上一句/上一词。

## `--fix` 自动修复为什么是安全的

新边界 = `quiet_min` 对应的时间点 + 一点点缓冲（默认0.02秒）。这个新边界
**只可能落在"已经独立测量确认是真正安静"的位置**，不可能反过来切进
上一句/上一词还在响的真实内容里——最坏情况只是"这次判断错了，其实
没有真实内容需要往后让"，后果顶多是给下一句/下一词的开头多留了一点点
无害的静音缓冲，不会导致新的内容丢失。这跟"人工估一个大概的新边界"
不是同一个风险等级，所以量大的时候可以放心批量 `--fix`，不需要像
手工改边界那样每一处都单独人工核实过才敢改。

**但 `--fix` 不是"改完就不用管了"**：批量改完之后仍然要做本 SKILL.md
一直强调的最终验证——用 `verify_clips.py` 做内容校验，并且（这是这次
新增的经验）**把连续几个相邻的已发布 clip 拼接起来整体转写**，确认
拼接后的文本完整、连续、顺序正确，不能只信任这个工具自己报告"改好了"。

## 已知的规模性发现（写这个工具的直接起因）

真实案例（textbook-sjp-zg-l15）：生词表 104 个词首尾零间隔相连，这个工具
一次性对 103 个内部边界跑一遍，发现 **96 个都存在不同程度的"边界晚于
真实静音点"**（0.02~0.33秒不等，部分超过 40dB 的剧烈跳变）。根因是
`refine_boundaries.py` 的 `biased_split_time()` 函数虽然设计上"偏向让
下一个词/句多分到停顿"，但它的计算基准（前一个词/句的 Whisper 词级
结束时间戳）本身经常系统性偏晚——公式没错，基准点不可靠。这不是这一课
独有的问题，**任何用 `align_group()` 处理过的生词表/句子分组都可能受
影响**，尤其是生词表这种"零间隔连续朗读"的材料（自然停顿本来就短，
基准点的系统性偏差占比更明显）。

**结论：生成页面之后，不能只满足于"人工听几个抽查、或者等用户反馈"，
应该把这个工具当成 `verify_clips.py`/`verify_quiz_ids.py` 同等级别的
必做项，对会话/课文/生词全部tab的全部内部边界跑一遍，`--fix` 批量修正
之后再走一遍拼接转写终验**——具体接入到 SKILL.md 流程里的位置见"生成
页面之后的边界质检"一节。
"""
import sys
import os
import subprocess
import wave
import math
import struct
import json
import argparse
import imageio_ffmpeg

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def rms_window(audio_path, ss, dur, frame_ms):
    tmp = "audit_quietpoint_probe.wav"
    subprocess.run(
        [FFMPEG, "-y", "-ss", str(max(0, ss)), "-t", str(dur), "-i", audio_path,
         "-ar", "16000", "-ac", "1", tmp],
        capture_output=True
    )
    w = wave.open(tmp, "rb")
    n = w.getnframes()
    data = w.readframes(n)
    w.close()
    try:
        os.remove(tmp)
    except OSError:
        pass
    samples = struct.unpack("<%dh" % (len(data) // 2), data)
    frame_len = max(1, int(16000 * frame_ms / 1000))
    out = []
    for i in range(0, len(samples) - frame_len, frame_len):
        chunk = samples[i:i + frame_len]
        rms = math.sqrt(sum(s * s for s in chunk) / len(chunk)) if chunk else 0
        db = 20 * math.log10(rms / 32768 + 1e-9)
        out.append((ss + i / 16000, round(db, 1)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("enriched_json")
    ap.add_argument("audio")
    ap.add_argument("--frame-ms", type=int, default=5)
    ap.add_argument("--search-back", type=float, default=0.35,
                     help="边界往前找安静点的搜索范围（秒）")
    ap.add_argument("--search-front", type=float, default=0.03,
                     help="搜索范围不包含紧贴边界的这一小段（秒），避免把边界本身的过渡帧当成安静点")
    ap.add_argument("--rise-threshold", type=float, default=6.0,
                     help="rise超过这个值（dB）才算可疑")
    ap.add_argument("--loud-threshold", type=float, default=-40.0,
                     help="边界处响度必须超过这个值（dB）才算可疑，排除两边都很安静的正常波动")
    ap.add_argument("--margin", type=float, default=0.02,
                     help="--fix 时，新边界=安静点+这个缓冲（秒）")
    ap.add_argument("--fix", action="store_true", help="直接把修正结果写回 enriched_json")
    ap.add_argument("--report", default=None, help="报告输出路径，不给就打印到stdout")
    args = ap.parse_args()

    data = json.load(open(args.enriched_json, encoding="utf-8"))
    sentences = data["sentences"]
    win = args.search_back + 0.25

    lines = []
    flagged = []
    for i in range(len(sentences) - 1):
        cur = sentences[i]
        nxt = sentences[i + 1]
        B = cur["end"]
        vals = rms_window(args.audio, B - args.search_back - 0.05, win, args.frame_ms)
        if len(vals) < 10:
            continue
        at_b = min(vals, key=lambda x: abs(x[0] - B))[1]
        search = [(t, db) for t, db in vals if B - args.search_back <= t <= B - args.search_front]
        if not search:
            continue
        min_t, min_db = min(search, key=lambda x: x[1])
        rise = round(at_b - min_db, 1)
        is_flag = rise > args.rise_threshold and at_b > args.loud_threshold
        tag = " <<<FLAG" if is_flag else ""
        lines.append(
            f'{nxt["id"]:4d} {cur["text"][:14]:14s}->{nxt["text"][:14]:14s} '
            f'B={B:8.2f} quiet_min_t={min_t:8.3f}({min_db:6.1f}dB) at_B={at_b:6.1f}dB rise={rise:5.1f}{tag}'
        )
        if is_flag:
            flagged.append((i, min_t))

    summary = f"共检查 {len(sentences) - 1} 个内部边界，{len(flagged)} 处可疑（rise>{args.rise_threshold}dB 且 at_B>{args.loud_threshold}dB）"
    out = "\n".join(lines) + "\n\n" + summary + "\n"
    if args.report:
        open(args.report, "w", encoding="utf-8").write(out)
        print(f"报告写入 {args.report}；{summary}")
    else:
        print(out)

    if args.fix and flagged:
        for i, min_t in flagged:
            new_b = round(min_t + args.margin, 2)
            sentences[i]["end"] = new_b
            sentences[i + 1]["start"] = new_b
        json.dump(data, open(args.enriched_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"--fix：已把 {len(flagged)} 处边界改为各自的安静点+{args.margin}秒，写回 {args.enriched_json}")
        print("注意：句子（非生词）如果带 char_times，这里不会重算——改完请照常跑一遍")
        print("`apply_manual_overrides.py`（若边界来自那份文件的同一份 manual_overrides）")
        print("或者手动确认 char_times 仍落在新的 [start,end] 范围内，再 recut_clips.py + patch_sentence_tokens.py。")


if __name__ == "__main__":
    main()
