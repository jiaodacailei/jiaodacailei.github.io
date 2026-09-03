# -*- coding: utf-8 -*-
"""
用法：
  python build_exam_audio.py <data.js路径> <audio输出目录> [--start-from N] [--limit N]

给build_exam_data.py生成的data.js（audio字段全是null的那版）逐条合成TTS
音频（edge-tts, ja-JP-NanamiNeural，跟2020-12案例同一个voice）+ 用
faster-whisper对齐拿到时长/逐字符时间戳（跟读高亮用），原地改data.js
把null都填上真实audio路径/duration/char_times token的t字段，音频文件
写进<audio输出目录>。

**跑的时间很长**（2020-12那次550条约90分钟）——`--start-from`/`--limit`
支持断点续跑：脚本会先打印总条数，可以先跑一小批(--limit 20)确认没问题
再跑全量；也可以中途中断后用`--start-from`从上次停的地方接着跑（判断
"是否已经跑过"靠检查对应audio文件是否已存在，不是靠改data.js里的标记，
所以可以反复安全重跑，已经生成过的条目会被跳过，不会重新烧TTS配额）。

## 条目收集规则（跟build_exam_data.py里各mondai类型的结构一一对应）

- 有`stem`字段（mondai 1-5,7,8）且`stem.tokens`非空：合成一条，文件名
  `q{id}_stem.mp3`。
- 有`stemWord`字段（mondai 6）：合成一条，`q{id}_stem.mp3`。
- `options[i]`有`tokens`（大多数mondai）：合成一条，`q{id}_opt{idx}.mp3`。
- `options[i]`有`sentences`（mondai 6专属，选项是完整句甚至多句）：每句
  合成一条，`q{id}_opt{idx}_s{n}.mp3`。
- `block.passageSentences`（mondai 9-14有段落的这几个大题）：每句合成
  一条，文件名`mondai{M}_block{k}_s{n}.mp3`（k是这个mondai内部第几个
  block，从1开始）。mondai9的`passageSentencesBlank`不合成（那份数据
  没有对应的真实"挖空后"语音场景，只用来渲染，音频用填好版
  `passageSentences`那份）。
"""
import sys
import os
import re
import json
import asyncio
import argparse
import tempfile
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from refine_boundaries import align_group  # noqa: E402
from build_page import normalize_numbers  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VOICE = "ja-JP-NanamiNeural"


def plain_text(tokens):
    return "".join(t["text"] for t in tokens if t.get("text") != "\n")


def collect_items(data):
    """返回[(filename, text, setter)]列表，setter(audio_rel, duration, char_times)
    负责把结果写回对应的dict字段——用闭包而不是返回路径描述符，避免另外
    写一套"按路径改json"的通用逻辑，两边字段结构差异太大不值得抽象。"""
    items = []

    def add(filename, tokens, target):
        text = plain_text(tokens)
        if not text:
            return

        def setter(audio_rel, duration, char_times, _target=target):
            _target["audio"] = audio_rel
            _target["duration"] = duration
            if char_times:
                ti = 0
                for t in _target_tokens(_target):
                    if t.get("text") == "\n":
                        continue
                    n = len(t["text"])
                    if ti < len(char_times):
                        t["t"] = char_times[ti]
                    ti += n

        items.append((filename, text, setter))

    def _target_tokens(target):
        return target.get("tokens", [])

    for m in data["mondaiList"]:
        mnum = m["mondai"]
        for bi, b in enumerate(m["blocks"], start=1):
            for s in b.get("passageSentences", []):
                if s.get("tokens"):
                    idx = b.setdefault("_pcount", 0) + 1
                    b["_pcount"] = idx
                    add("mondai{}_block{}_s{}.mp3".format(mnum, bi, idx), s["tokens"], s)
            for q in b["questions"]:
                qid = q["id"]
                if q.get("stem") and q["stem"].get("tokens"):
                    add("q{}_stem.mp3".format(qid), q["stem"]["tokens"], q["stem"])
                if q.get("stemWord") and q["stemWord"].get("tokens"):
                    add("q{}_stem.mp3".format(qid), q["stemWord"]["tokens"], q["stemWord"])
                for opt in q.get("options", []):
                    if "tokens" in opt:
                        add("q{}_opt{}.mp3".format(qid, opt["idx"]), opt["tokens"], opt)
                    elif "sentences" in opt:
                        for si, sent in enumerate(opt["sentences"], start=1):
                            add("q{}_opt{}_s{}.mp3".format(qid, opt["idx"], si), sent["tokens"], sent)
    # 清掉临时计数字段，不留进最终data.js
    for m in data["mondaiList"]:
        for b in m["blocks"]:
            b.pop("_pcount", None)
    return items


async def _synth(text, out_path):
    import edge_tts

    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(out_path)


def synth_tts(text, out_path):
    asyncio.run(_synth(text, out_path))


def probe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    try:
        return round(float(r.stdout.strip()), 3)
    except ValueError:
        return None


def whisper_align(model, wav_path, text):
    segments, _ = model.transcribe(
        wav_path, language="ja", word_timestamps=True, beam_size=5,
        condition_on_previous_text=False,
    )
    words = []
    for seg in segments:
        if seg.words:
            words.extend(seg.words)
    if not words:
        return None
    _split, char_times_per_sentence, _edge_start, _edge_end = align_group(
        [{"text": text}], words, 0.0
    )
    if char_times_per_sentence is None:
        return None
    return char_times_per_sentence[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_js")
    ap.add_argument("audio_dir")
    ap.add_argument("--start-from", type=int, default=0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--count-only", action="store_true")
    args = ap.parse_args()

    raw = open(args.data_js, encoding="utf-8").read()
    prefix = raw[: raw.index("{")]
    body = raw[raw.index("{") :]
    body = re.sub(r";\s*$", "", body.strip())
    data = json.loads(body)

    items = collect_items(data)
    print("total audio items:", len(items))
    if args.count_only:
        return

    os.makedirs(args.audio_dir, exist_ok=True)

    from faster_whisper import WhisperModel

    model = WhisperModel("medium", device="cpu", compute_type="int8")
    tmp_wav = os.path.join(tempfile.gettempdir(), "exam_audio_tmp.wav")

    end = len(items) if args.limit is None else min(len(items), args.start_from + args.limit)
    ok, fallback, failed = 0, 0, 0
    for i in range(args.start_from, end):
        filename, text, setter = items[i]
        out_path = os.path.join(args.audio_dir, filename)
        if os.path.exists(out_path):
            # 已经跑过（断点续跑场景）——duration/char_times 目前是 None，
            # 用已有文件重新探测/对齐一遍，保持跟第一次跑完全一致的结果。
            pass
        else:
            try:
                synth_tts(text, out_path)
            except Exception as e:
                print(f"[{i}] TTS FAILED {filename}: {e}")
                failed += 1
                continue

        duration = probe_duration(out_path)
        subprocess.run(
            ["ffmpeg", "-y", "-i", out_path, "-ar", "16000", "-ac", "1", tmp_wav],
            capture_output=True,
        )
        char_times = whisper_align(model, tmp_wav, text)
        if char_times is None:
            fallback += 1
            # 对齐失败就线性插值兜底，不留 null（没有跟读高亮，但播放本身没问题）
            n = len(text)
            if duration and n > 0:
                char_times = [round(duration * k / n, 2) for k in range(n)]
        else:
            ok += 1
        setter(filename, duration, char_times)

        if (i + 1) % 25 == 0 or i + 1 == end:
            print(f"progress: {i + 1}/{len(items)} (aligned {ok}, fallback {fallback}, failed {failed})")

    os.remove(tmp_wav) if os.path.exists(tmp_wav) else None

    out = prefix + json.dumps(normalize_numbers(data), ensure_ascii=False, indent=2) + ";\n"
    with open(args.data_js, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print("wrote", args.data_js)
    print(f"final: aligned {ok}, fallback {fallback}, failed {failed}, total {end - args.start_from}")


if __name__ == "__main__":
    main()
