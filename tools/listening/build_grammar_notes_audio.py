# -*- coding: utf-8 -*-
"""用法：
  python build_grammar_notes_audio.py <data.js路径> [--audio-dir <目录>]
      [--start-from N] [--limit N]

给`build_grammar_notes_tab.py`生成的"语法与表达"tab里那些没匹配上本课
真实会话/课文录音、audio还是null的补充例句（教材app自己补写的例句，本课
录音里没有对应片段）合成TTS音频（edge-tts, ja-JP-NanamiNeural，跟
`build_exam_audio.py`同一个voice）+ faster-whisper对齐拿到跟读高亮用
的逐字符时间戳，原地改data.js把这些句子的audio/tokens[].t补上。

**这些例句本来就不是这一课的真人朗读**（是教材配套app为了讲解语法另外
写的补充例句，跟会话/课文原文是两回事），合成出来是edge-tts的机器音，
跟这一课其余会话/课文/生词的真人录音音色不一样——这是预期的、没法避免
的，不是bug，只是听感上能分辨出"这几句是后配的"。

同一句话如果同时也是"生词"tab里某个词条的例句（`sentenceAudio`目前是
null，因为当初生成"语法与表达"tab时这句没匹配上真句子、自然也没有
sentenceAudio），合成完直接把同一个audio路径也填进对应生词卡的
`sentenceAudio`，不重复合成——两边引用的是同一句话。

跟`build_exam_audio.py`一样支持`--start-from`/`--limit`断点续跑：判断
"是不是已经跑过"靠检查对应`audio/seg-{id:03d}.mp3`是否已存在，不是靠
data.js里的标记，可以反复安全重跑。
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
    """返回[(filename, text, setter)]——只收"语法与表达"tab里audio为null
    的句子；还额外建一份text->[对应生词/quiz里需要同步sentenceAudio的
    setter]映射，音频合成完之后统一回填。"""
    items = []
    sentence_audio_setters = {}  # text -> [setter(audio_rel), ...]

    grammar_tab = next((t for t in data["tabs"] if t["mondai"] == "语法与表达"), None)
    if grammar_tab is None:
        raise SystemExit("data.js里没有\"语法与表达\"tab，先跑build_grammar_notes_tab.py")

    for q in grammar_tab["questions"]:
        for s in q["sentences"]:
            if s.get("audio") is not None:
                continue
            text = plain_text(s["tokens"])
            if not text:
                continue

            def setter(audio_rel, duration, char_times, _s=s):
                _s["audio"] = audio_rel
                _s["duration"] = duration
                if char_times:
                    ti = 0
                    for t in _s["tokens"]:
                        if t.get("text") == "\n":
                            continue
                        n = len(t["text"])
                        if ti < len(char_times):
                            t["t"] = char_times[ti]
                        ti += n

            items.append(("seg-{:03d}.mp3".format(s["id"]), text, setter))

    # 生词tab里sentenceAudio为null、且quizSentence文本能在上面收集到的句子
    # 里精确匹配上的，音频合成完直接同步填进去，不重复合成同一句话。
    vocab_tab = next((t for t in data["tabs"] if t["mondai"] == "生词"), None)
    if vocab_tab:
        for q in vocab_tab["questions"]:
            for s in q["sentences"]:
                if "sentenceAudio" not in s or s.get("sentenceAudio") is not None:
                    continue
                qs = s.get("quizSentence")
                if not qs:
                    continue
                sentence_audio_setters.setdefault(qs, []).append(
                    lambda audio_rel, _s=s: _s.__setitem__("sentenceAudio", audio_rel)
                )

    return items, sentence_audio_setters


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
    ap.add_argument("--audio-dir", default=None)
    ap.add_argument("--start-from", type=int, default=0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--count-only", action="store_true")
    args = ap.parse_args()

    audio_dir = args.audio_dir or os.path.join(os.path.dirname(os.path.abspath(args.data_js)), "audio")

    raw = open(args.data_js, encoding="utf-8").read()
    prefix = raw[: raw.index("{")]
    body = raw[raw.index("{") :]
    body = re.sub(r";\s*$", "", body.strip())
    data = json.loads(body)

    items, sentence_audio_setters = collect_items(data)
    print("total audio items:", len(items))
    print("生词/quiz里等着同步sentenceAudio的句子:", len(sentence_audio_setters))
    if args.count_only:
        return

    os.makedirs(audio_dir, exist_ok=True)

    from faster_whisper import WhisperModel

    model = WhisperModel("medium", device="cpu", compute_type="int8")
    tmp_wav = os.path.join(tempfile.gettempdir(), "grammar_notes_audio_tmp.wav")

    end = len(items) if args.limit is None else min(len(items), args.start_from + args.limit)
    ok, fallback, failed = 0, 0, 0
    for i in range(args.start_from, end):
        filename, text, setter = items[i]
        out_path = os.path.join(audio_dir, filename)
        if not os.path.exists(out_path):
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
            n = len(text)
            if duration and n > 0:
                char_times = [round(duration * k / n, 2) for k in range(n)]
        else:
            ok += 1
        audio_rel = "audio/" + filename
        setter(audio_rel, duration, char_times)
        for cb in sentence_audio_setters.get(text, []):
            cb(audio_rel)

        if (i + 1) % 10 == 0 or i + 1 == end:
            print(f"progress: {i + 1}/{len(items)} (aligned {ok}, fallback {fallback}, failed {failed})")

    os.remove(tmp_wav) if os.path.exists(tmp_wav) else None

    out = prefix + json.dumps(normalize_numbers(data), ensure_ascii=False, indent=2) + ";\n"
    with open(args.data_js, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print("wrote", args.data_js)
    print(f"final: aligned {ok}, fallback {fallback}, failed {failed}, total {end - args.start_from}")


if __name__ == "__main__":
    main()
