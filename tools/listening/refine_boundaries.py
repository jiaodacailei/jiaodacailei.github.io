# -*- coding: utf-8 -*-
"""
用法：python refine_boundaries.py <原始音频> <enriched.json> <输出 enriched.json>

早期版本只修"一个 Whisper 原始片段被多句共享"这一小撮情况，其余句子保持
`merge_groups.py` 里 `resolve_overlaps()` 给出的锚点中点边界不动。但实测发现：
就算某句独占一个 raw_id，Whisper 自己给这个 raw 片段打的起止时间戳也可能不准、
甚至和相邻 raw 片段互相重叠（例如"うん。..."和"...行くんだ。"分属两个不同 raw_id，
但后一个的起始时间戳比前一个的结束时间戳还早了近2秒）——这种情况下锚点中点
算法切出来的点必然落在错误的位置，会出现"上一句结尾带了下一句的音头、下一句
开头又丢了自己的音头"这种边界串门。这类问题不局限于"共享片段"，任何相邻两句
之间都可能发生。

**因此现在改成：以每道题（大问+小题）为单位，统一用文本对齐重新定位题目内部
所有句子边界**，不再区分"是否共享 raw_id"：
  1. 按 mondai+question 把句子分组，每组算出这道题的整体时间跨度（组内最早的
     start 到最晚的 end）
  2. 对这道题的完整跨度重新跑一次 word_timestamps=True 转写，拿到这段音频里
     实际识别出的每个词的文字和时间戳
  3. 把这道题里全部句子 AI 校对过的"期望文本"依次拼起来、把重新识别出的词的
     文字也拼起来，用 `difflib.SequenceMatcher` 做序列对齐，按**实际内容**
     （而不是字数比例、也不是检测停顿）找出每两句之间的真实分界点落在识别
     文本的哪个位置，再映射回对应的词、取词边界时间戳
  4. 对齐质量不够（识别文字跟校对文字差太多）就针对这道题回退成字数比例切分，
     不强行相信一个烂对齐；题目整体的第一句起点/最后一句终点固定不变，只重新
     分配内部边界
  5. 单句题目（题目内只有一句）没有内部边界要切，直接跳过、原样保留

**为什么最后选了"文本对齐"而不是"字数比例"或"检测停顿"**——踩过两次坑，见
`.claude/skills/jp-listening-page/SKILL.md` 的"常见坑"，这里只记结论：
  - 检测停顿（间隔阈值）：会把句子内部的逗号停顿也当成句子边界，错位会一路级联。
  - 字数比例：语速不均匀时不准，尤其是两句衔接特别紧、边界附近发音又接近的场景
    （比如"...ございます。"和下一句"おはよう。"都在"お"附近），实测会出现
    "上一句结尾多了字、下一句开头少了字"这种边界"串门"的问题。整题范围用字数
    比例还会对本来就切得准的句子引入新的偏移（drift）。
  - 文本对齐：不管语速、不管边界发音像不像，直接按"识别出来的字"和"校对过的字"
    做匹配，边界该在哪就在哪；如果原来的边界本来就准，对齐结果会落在同一位置，
    不会凭空引入新偏移——所以可以放心地把它用到全部句子上，而不只是可疑片段。
"""
import sys
import json
import difflib
import subprocess
import imageio_ffmpeg
from faster_whisper import WhisperModel

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
MIN_ALIGNMENT_COVERAGE = 0.45  # 匹配上的字符比例低于这个就认为对齐不可信，回退


def proportional_split(members, words):
    """按字数比例分配词数，兜底用（对齐失败时才用这个）。"""
    total_chars = sum(max(len(s["text"]), 1) for s in members)
    cum_chars = 0
    word_splits = []
    for s in members[:-1]:
        cum_chars += max(len(s["text"]), 1)
        idx = round(cum_chars / total_chars * len(words))
        idx = max(1, min(idx, len(words) - 1))
        if word_splits and idx <= word_splits[-1]:
            idx = word_splits[-1] + 1
        word_splits.append(min(idx, len(words) - 1))
    return [(words[i - 1].end + words[i].start) / 2 for i in word_splits]


def alignment_split(members, words):
    """用识别文字 vs 校对文字做序列对齐，按实际内容定位切分点。对齐质量不够返回 None。"""
    recognized_text = ""
    char_to_word = []  # 第 i 个字符属于哪个 word 的下标
    for wi, w in enumerate(words):
        wtext = (w.word or "").strip()
        recognized_text += wtext
        char_to_word.extend([wi] * len(wtext))
    if not recognized_text:
        return None

    expected_texts = [s["text"] for s in members]
    expected_text = "".join(expected_texts)

    sm = difflib.SequenceMatcher(None, expected_text, recognized_text, autojunk=False)
    blocks = sm.get_matching_blocks()
    matched_chars = sum(b.size for b in blocks)
    if len(expected_text) == 0 or matched_chars / len(expected_text) < MIN_ALIGNMENT_COVERAGE:
        return None

    def expected_pos_to_recognized_pos(target_a):
        # 期望文本里句子边界处常有「」。这类标点，识别文本里完全没有对应字符
        # （Whisper 不转写标点）——如果直接从上一个匹配块按原始字符差"外推"，
        # 会把这些有去无回的标点字符数也算进去，导致切分点系统性偏晚（真实案例：
        # 003 结尾多出的"お"就是这么来的）。正确做法是在"上一个匹配块结束点"和
        # "下一个匹配块开始点"之间按比例插值，如果两者在识别文本里的位置相同
        # （比如标点两边紧挨着都对应同一个识别位置），插值结果自然就是那个位置，
        # 不会被标点字符数拖着往后走。
        prev_end_a, prev_end_b = 0, 0
        for b in blocks:
            if b.size == 0:
                continue
            if b.a <= target_a <= b.a + b.size:
                return b.b + (target_a - b.a)
            if target_a < b.a:
                gap_a = b.a - prev_end_a
                if gap_a <= 0:
                    return prev_end_b
                frac = (target_a - prev_end_a) / gap_a
                return round(prev_end_b + frac * (b.b - prev_end_b))
            prev_end_a, prev_end_b = b.a + b.size, b.b + b.size
        return prev_end_b

    cum = 0
    split_times = []
    prev_word_idx = 0
    for s in members[:-1]:
        cum += len(s["text"])
        rec_pos = expected_pos_to_recognized_pos(cum)
        rec_pos = max(0, min(rec_pos, len(recognized_text) - 1))
        wi = char_to_word[rec_pos] if rec_pos < len(char_to_word) else len(words) - 1
        wi = max(prev_word_idx + 1, min(wi, len(words) - 1))
        t = (words[wi - 1].end + words[wi].start) / 2
        split_times.append(t)
        prev_word_idx = wi
    return split_times


def main():
    audio_path = sys.argv[1]
    in_enriched_path = sys.argv[2]
    out_enriched_path = sys.argv[3]

    enriched = json.load(open(in_enriched_path, encoding="utf-8"))
    sentences = enriched["sentences"]

    groups = {}
    for s in sentences:
        groups.setdefault((s["mondai"], s["question"]), []).append(s)

    multi = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"{len(groups)} questions total, {len(multi)} have multiple sentences to refine")

    model = WhisperModel("medium", device="cpu", compute_type="int8")
    clip_path = "refine_clip_tmp.wav"

    fixed, fallback_count = 0, 0
    for (mondai, question), members in multi.items():
        members.sort(key=lambda s: (s["start"], s["end"]))
        span_start = min(s["start"] for s in members)
        span_end = max(s["end"] for s in members)

        subprocess.run(
            [FFMPEG, "-y", "-ss", str(span_start), "-t", str(span_end - span_start),
             "-i", audio_path, "-ar", "16000", "-ac", "1", clip_path],
            capture_output=True
        )
        # condition_on_previous_text=False：不给这么大不给这么长的片段（问题跨度常有
        # 一两分钟）不加这个参数，Whisper 偶尔会陷入复读循环（把开头一句话反复输出
        # 好几遍、后面真正的对话内容整段丢失），实测在"問題1 2番"上复现过，识别文本
        # 覆盖率只有 17%，导致回退成字数比例、切出大量近零时长句子。关掉"用前文
        # 状态影响当前解码"后恢复正常。
        segments, _ = model.transcribe(
            clip_path, language="ja", word_timestamps=True, beam_size=5,
            condition_on_previous_text=False,
        )
        words = []
        for seg in segments:
            if seg.words:
                words.extend(seg.words)

        n = len(members)
        if len(words) < n:
            print(f"  {mondai} {question} {span_start}-{span_end}: only {len(words)} words for {n} sentences, skip")
            continue

        time_splits = alignment_split(members, words)
        method = "alignment"
        if time_splits is None:
            time_splits = proportional_split(members, words)
            method = "proportional-fallback"
            fallback_count += 1

        bounds = [0.0] + time_splits + [span_end - span_start]
        # 保证单调递增，避免对齐结果偶尔给出非递增的切分点
        for i in range(1, len(bounds) - 1):
            if bounds[i] <= bounds[i - 1]:
                bounds[i] = bounds[i - 1] + 0.05
        bounds = [span_start + b for b in bounds]

        for i, s in enumerate(members):
            s["start"], s["end"] = round(bounds[i], 2), round(bounds[i + 1], 2)
            fixed += 1
        print(f"  {mondai} {question} {span_start}-{span_end}: {n} sentences [{method}] -> "
              f"{[round(b, 2) for b in bounds]}")

    sentences.sort(key=lambda s: s["start"])
    for i, s in enumerate(sentences, 1):
        s["id"] = i

    json.dump(enriched, open(out_enriched_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Refined {fixed} sentence boundaries ({fallback_count} questions used proportional fallback), "
          f"left {len(sentences) - fixed} untouched, wrote {out_enriched_path}")


if __name__ == "__main__":
    main()
