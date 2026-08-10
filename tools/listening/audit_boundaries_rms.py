# -*- coding: utf-8 -*-
"""
用法：
  python audit_boundaries_rms.py <enriched_combined.json> <原始音频文件>
      <输出报告.txt> [--frame-ms 10] [--floor-margin 16]

共享工具（`jp-textbook-lesson` 用）：对 `enriched.json` 里每一个句子边界
（含相邻两句共享的内部切分点、每个题目分组的 edge_start/edge_end）跑一次
逐帧 RMS 能量剖面，判断这个时间点本身是不是正好落在一段连续语音的内部——
这是 `verify_clips.py` 的整体相似度校验查不出来的一类 bug（丢的只是句子
开头/结尾一两个音节，剩下的部分转写依然对得上，相似度不会掉到警戒线以下）。
补充在同一课（textbook-sjp-zg-l14）真实踩过的坑：

## 这个脚本能查、`verify_clips.py` 查不出来的

- **句尾多切进下一句开头几十到几百毫秒**——切出来的整句转写依然完整、
  正确，只是结尾/开头多了/少了一点点声音，`verify_clips.py` 的相似度
  比对完全无感。真实案例：`あれ，そんなに気を使わなくてよかったのに`
  结尾多切进了`いいえ`开头的`い`音，两条整句转写都"正常"，只有本脚本
  的边界级检查能发现。

## 用法上必须记住的四条教训（这一课真实踩过，不是理论风险）

1. **不要只看边界"落在语音内部的百分比"来判断严重程度，哪怕只有5~10%
   也可能是真的能听出来的 bug**——最早把 `<10%` 的命中都当成"可忽略的
   插值误差"跳过，结果其中至少一处（`27.53s` 那处边界）就是用户反馈的
   真实 bug，重新做更细粒度（10ms）分析后发现真实起音比边界早了0.09秒。
   报告里所有命中"边界落在语音内部"的条目都要人工过一遍，不能凭百分比
   数字自己筛掉一批。
2. **报告"边界正好落在一段连续语音burst内部"，不代表这段burst的身份就是
   你以为的那一句——必须额外跑一次覆盖这个burst前后至少几秒的word-level
   转写来确认这段burst到底是谁的内容，不能凭"离哪句更近"猜**。真实案例：
   一段响亮的burst被误认为是`かい`（"…連絡があるかい"的结尾）的自然拖音，
   实际上word-level转写显示`かい`早在这段burst开始前0.13秒就已经结束了——
   这段burst其实是完全独立的一段声音（"ええ"，太短/太不清晰导致Whisper
   没能把它转写成词），只是恰好挨着`かい`，乍看像是它的尾音。**这个坑
   连续踩了两轮**：第一轮完全没意识到这段burst的存在（判断"这句和下一句
   之间就是纯静音，没有真实分界点"，还因此把两句合并成一张卡片），第二
   轮虽然重新拿到了这段burst的时间范围，却想当然把它归给了相邻的已知句子，
   没有用word-level转写去确认它到底是谁——**两轮判断错误的根本原因相同：
   看到一段能量剖面，没有去问"这段声音真正对应的是哪个词"，就先入为主
   套用了"离哪句最近就是哪句"这个假设**。
3. **20ms 帧长的能量剖面粗糙到会把一整段"上一句尾音+短促应答词+静音+
   下一句开头"全部糊成一个burst，看不出内部其实还有独立的短促内容**——
   `ええ`这类极短促、几乎不带停顿的应答词，真实持续时间可能只有150~
   200毫秒，混在相邻两句的自然拖音里用20ms帧几乎不可能分辨出层次，必须
   用本脚本默认的10ms（甚至更细）帧长，且要在怀疑的区间里手工画出逐帧
   数值人工读，不能只信自动burst切分算法的结果。
4. **反过来，RMS 能量阈值判断也会有假阳性——一个词内部如果有天然偏轻/
   偏虚的元音拖长或者辅音过渡（比如"手洗い"里"洗い"这一段），振幅可能
   短暂低于相对阈值，被误判成"这里是两个词之间的静音间隔"，实际上从头到
   尾都是同一个词连贯的发音，中间根本没有真实的词边界**。真实案例：本课
   生词"うがい/手洗い"的边界一度被本脚本判定成有0.15秒的问题（RMS显示
   一段"静音"），但① 这两个词各自单独转写完整、干净，没有互相缺字/多字；
   ② 用**给够前置上下文（从うがい自己的真实起点开始，不能从窗口中途截断）
   的word-level转写**重新核实，"うがい"和"手洗い"紧密相连、中间时间戳
   完全吻合当前边界，没有任何缺口。两项独立证据都支持"边界本身没问题"，
   只有RMS一项显示"有问题"，最终判定RMS这次是假阳性，不需要改。**结论**：
   RMS判定"边界落在语音内部"或者"边界两侧有静音间隔"都不能单独当作最终
   结论，必须至少用一次**给够上下文**的word-level转写交叉核实（窗口没给够
   前置上下文的word-level转写本身也不可靠，容易输出完全对不上的乱序结果，
   见真实案例：同一个区间窄窗口转写给出的时间戳跟宽窗口转写完全对不上），
   两种方法互相佐证了才能下结论，任何一种单独出结果都不能直接采信。

报告只标出可疑边界+给出参考的word-level转写命令提示，不自动下结论、
不自动改任何文件——每一条命中都需要人工按上面四条教训核实清楚。
"""
import sys
import os
import subprocess
import tempfile
import wave
import math
import struct
import json
import argparse
import imageio_ffmpeg

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def rms_profile(audio_path, start, end, frame_ms):
    tmp = os.path.join(tempfile.gettempdir(), "audit_boundaries_rms_probe.wav")
    subprocess.run(
        [FFMPEG, "-y", "-ss", str(max(0, start)), "-t", str(end - start), "-i", audio_path,
         "-ar", "16000", "-ac", "1", tmp],
        capture_output=True
    )
    w = wave.open(tmp, "rb")
    n = w.getnframes()
    data = w.readframes(n)
    w.close()
    samples = struct.unpack("<%dh" % (len(data) // 2), data)
    frame_len = int(16000 * frame_ms / 1000)
    out = []
    for i in range(0, len(samples) - frame_len, frame_len):
        chunk = samples[i:i + frame_len]
        rms = math.sqrt(sum(s * s for s in chunk) / len(chunk)) if chunk else 0
        db = 20 * math.log10(rms / 32768 + 1e-9)
        out.append((start + i / 16000, round(db, 1)))
    return out


def find_bursts(prof, floor_margin, min_gap=0.10):
    floor = min(db for t, db in prof)
    threshold = floor + floor_margin
    bursts = []
    cur_start = None
    last_t = None
    for t, db in prof:
        if db > threshold:
            if cur_start is None:
                cur_start = t
            last_t = t
        else:
            if cur_start is not None and (t - last_t) > min_gap:
                bursts.append((cur_start, last_t))
                cur_start = None
    if cur_start is not None:
        bursts.append((cur_start, last_t))
    return bursts


def audit_boundary(audio_path, b, frame_ms, floor_margin, window=1.2):
    prof = rms_profile(audio_path, b - window, b + window, frame_ms)
    bursts = find_bursts(prof, floor_margin)
    inside = [burst for burst in bursts if burst[0] <= b <= burst[1]]
    if inside:
        onset, offset = inside[0]
        frac = (b - onset) / (offset - onset) if offset > onset else 0
        return {
            "status": "INSIDE_BURST",
            "burst": (round(onset, 3), round(offset, 3)),
            "frac": round(frac * 100),
        }
    before = [burst for burst in bursts if burst[1] < b]
    after = [burst for burst in bursts if burst[0] > b]
    return {
        "status": "OK",
        "gap_before": round(b - before[-1][1], 3) if before else None,
        "gap_after": round(after[0][0] - b, 3) if after else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("enriched_json")
    ap.add_argument("audio_path", help="这一段原始音频文件（不是切好的 seg-NNN.mp3，是 enriched.json 里 start/end 所在坐标系对应的那个完整音频）")
    ap.add_argument("out_report")
    ap.add_argument("--frame-ms", type=float, default=10.0, help="RMS帧长，默认10ms——20ms会把ええ这类短促应答词糊掉，见文件头部教训3")
    ap.add_argument("--floor-margin", type=float, default=16.0, help="判定burst的相对阈值=这段窗口的最低dB+这个margin")
    args = ap.parse_args()

    data = json.load(open(args.enriched_json, encoding="utf-8"))
    sentences = sorted(data["sentences"], key=lambda s: s["start"])
    seen = set()
    hits = []
    total = 0
    for s in sentences:
        for b in (s["start"], s["end"]):
            if b in seen:
                continue
            seen.add(b)
            total += 1
            result = audit_boundary(args.audio_path, b, args.frame_ms, args.floor_margin)
            if result["status"] == "INSIDE_BURST":
                hits.append((s["id"], b, result))

    with open(args.out_report, "w", encoding="utf-8") as f:
        f.write(f"共检查 {total} 个边界点，{len(hits)} 处边界落在语音内部（不代表都是bug，"
                f"逐条按文件头部四条教训人工核实——尤其不要因为百分比小就跳过，也不要单凭这份RMS"
                f"报告本身下结论，必须再用一次给够前置上下文的word-level转写交叉核实，两者都指向"
                f"同一个结论才算数）\n\n")
        for sid, b, result in hits:
            onset, offset = result["burst"]
            f.write(f"id~{sid} b={b:.2f} 落在burst({onset},{offset})第{result['frac']}%处 —— "
                    f"建议核实命令：python -c \"...transcribe ss={max(0,onset-2):.1f} t={offset-onset+4:.1f}...\"\n")
    print(f"wrote {len(hits)} suspect boundaries (of {total} total) to {args.out_report}")


if __name__ == "__main__":
    main()
