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
  4. 对齐质量不够（识别文字跟校对文字差太多）就针对这道题回退：多句题目的内部
     切分退回字数比例，题目整体的外边界（第一句起点/最后一句终点）保持原样——
     没有可信的对齐结果，不强行重新定位。
  5. 对齐质量够的情况下，题目整体的外边界（第一句起点/最后一句终点）**也会用
     对齐结果里第一个/最后一个真实匹配块重新定位**，不是"锁定不变"——早期版本
     假设外边界已经在更早的步骤（人工通读 items.json）里核实过、值得信任，只精修
     内部切分点。这个假设只对结构化材料成立，碰到从嘈杂录音里筛出来的单句（没有
     items.json 那道人工核实）就会暴露：外边界其实是 Whisper 粗转写的 segment
     边界，本来就不准，"锁定不变"等于把这份不准也锁死了，播放时每句开头/结尾会
     带一大截空白、完全没对齐。改成外边界也重新定位之后，结构化材料因为外边界
     本来就准，对齐结果会落在同一位置，不会引入新偏移，不会有回归；单句题目终于
     也能获得跟内部切分同等精度的边界。

同一次转写+对齐结果还顺带算出每句内部**逐字符的时间戳**（`char_times`），供页面
播放时高亮当前正在读的词——不管题目内是一句还是多句都会算，单句题目也不再跳过
（只是不需要切内部边界）。对齐质量不够时这部分退回线性插值（按字符位置比例在
句子自己的 start/end 之间估一个时间），不影响边界切分那部分的回退逻辑。

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


def biased_split_time(prev_end, next_start):
    """相邻两句之间的静音间隔取切分点时，不取正中点，而是偏向前一句结尾这一侧。

    真实案例（2021年12月N2 問題5 2番）：句尾是"ね。"这类词，下一句开头是"へー"
    这类语气词，Whisper 对语气词前的停顿判断经常偏晚（把停顿的一部分当成了语气词
    本身的时长，或者干脆把停顿和语气词合并成一个跨度很长的 token），取正中点会把
    这部分「多算的停顿」的一半划给前一句，导致前一句结尾带了一截空白甚至下一句的
    气声/语气词头部，下一句开头则被相应地削掉一截。人耳对「下一句开头被削」比
    「两句之间停顿稍微长一点」敏感得多，所以切分点往前一句这边靠：只吃掉停顿间隔
    的一小部分（间隔的 25%，最多 0.15 秒），剩下的停顿全部留给下一句当作起始静音。
    """
    gap = next_start - prev_end
    if gap <= 0:
        return prev_end
    return prev_end + min(0.15, gap * 0.25)


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
    return [biased_split_time(words[i - 1].end, words[i].start) for i in word_splits]


def build_char_to_word(words):
    recognized_text = ""
    char_to_word = []  # 第 i 个字符属于哪个 word 的下标
    for wi, w in enumerate(words):
        wtext = (w.word or "").strip()
        recognized_text += wtext
        char_to_word.extend([wi] * len(wtext))
    return recognized_text, char_to_word


def make_pos_mapper(blocks):
    """期望文本里的字符位置 -> 识别文本里的对应位置。

    期望文本里句子边界处常有「」。这类标点，识别文本里完全没有对应字符
    （Whisper 不转写标点）——如果直接从上一个匹配块按原始字符差"外推"，
    会把这些有去无回的标点字符数也算进去，导致切分点系统性偏晚（真实案例：
    003 结尾多出的"お"就是这么来的）。正确做法是在"上一个匹配块结束点"和
    "下一个匹配块开始点"之间按比例插值，如果两者在识别文本里的位置相同
    （比如标点两边紧挨着都对应同一个识别位置），插值结果自然就是那个位置，
    不会被标点字符数拖着往后走。
    """
    def expected_pos_to_recognized_pos(target_a):
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
    return expected_pos_to_recognized_pos


def align_group(members, words, span_start):
    """对一道题（不管只有一句还是有多句）算三件事，共用同一次 word-level 转写
    和同一套文本对齐结果，不用为了多个目的对同一段音频重复转写两次：

    - edge_start/edge_end：题目整体的起点/终点（相对 span_start 的时间）。早期版本
      这两个边界是"锁定不变"的——直接照抄传进来的 span_start/span_end，理由是
      "题目外边界已经在更早的步骤里人工核实过，值得信任"。但这个假设只对"经过
      items.json 人工通读确认"的结构化材料成立；碰到从嘈杂录音里筛出来的单句
      （没有这一步人工核实）就会暴露问题——传进来的边界就是 Whisper 粗转写的
      segment 边界，本来就不准，"锁定不变"等于把这份不准也锁死了，播放时明显能
      听到"每句开头/结尾一大截空白，完全没对齐"。所以现在改成：不管题目外边界
      传进来时准不准，都用对齐结果里**第一个/最后一个真实匹配块**对应的词边界
      重新定位——如果外边界本来就准，对齐结果会落在同一位置，不会引入新偏移
      （跟内部切分点当初改用文本对齐是同一个道理）；如果本来不准，这里能精确
      改过来，不用再假设"外边界不需要动"。
    - split_times：多句时，相邻句之间的切分点（原来 alignment_split 的算法）。
    - char_times_per_sentence：每句内部逐字符的时间戳（绝对时间，= span_start +
      该字符对应识别词的起始时间），给跟读高亮用——哪怕题目只有一句也需要这个，
      所以不能像切分点那样"只有多句才算"。

    对齐质量不够（识别文字跟校对文字差太多）返回 (None, None, None, None)，调用方
    按各自的兜底逻辑处理（split 退回字数比例，边界/char_times 退回原样/线性插值）。
    """
    recognized_text, char_to_word = build_char_to_word(words)
    if not recognized_text:
        return None, None, None, None

    expected_text = "".join(s["text"] for s in members)
    sm = difflib.SequenceMatcher(None, expected_text, recognized_text, autojunk=False)
    blocks = sm.get_matching_blocks()
    real_blocks = [b for b in blocks if b.size > 0]
    matched_chars = sum(b.size for b in real_blocks)
    if len(expected_text) == 0 or not real_blocks or matched_chars / len(expected_text) < MIN_ALIGNMENT_COVERAGE:
        return None, None, None, None

    pos_map = make_pos_mapper(blocks)

    def word_at(target_a, floor_word_idx=0):
        rec_pos = pos_map(target_a)
        rec_pos = max(0, min(rec_pos, len(recognized_text) - 1))
        wi = char_to_word[rec_pos] if rec_pos < len(char_to_word) else len(words) - 1
        return max(floor_word_idx, min(wi, len(words) - 1))

    # 逐字符时间戳：expected_text 里每个字符 -> 它所在识别词的起始时间（绝对时间）。
    # Whisper 给日语打的词级时间戳本来就接近逐字/逐音节粒度（"私""は""高""い"这种），
    # 同一个识别词内的字符共用它的起始时间已经够细，不用再做词内插值。
    char_times_flat = [
        round(span_start + words[word_at(p)].start, 2)
        for p in range(len(expected_text))
    ]

    # 题目外边界：直接用第一个/最后一个真实匹配块对应的词，不走 word_at()（那个是
    # 给"中间切分点"设计的插值逻辑，边界在两端时没有"前一个/后一个块"可插值，容易
    # 算错）——第一个匹配块的起点、最后一个匹配块的终点就是这道题内容在这段音频里
    # 实际开始/结束的地方，足够直接。
    first_b, last_b = real_blocks[0], real_blocks[-1]
    wi_first = char_to_word[first_b.b] if first_b.b < len(char_to_word) else 0
    last_rec_pos = last_b.b + last_b.size - 1
    wi_last = char_to_word[last_rec_pos] if last_rec_pos < len(char_to_word) else len(words) - 1
    wi_last = max(wi_first, wi_last)
    edge_start = round(words[wi_first].start, 2)
    edge_end = round(words[wi_last].end, 2)

    split_times = None
    if len(members) > 1:
        cum = 0
        split_times = []
        prev_word_idx = wi_first
        for s in members[:-1]:
            cum += len(s["text"])
            wi = word_at(cum, prev_word_idx + 1)
            split_times.append(biased_split_time(words[wi - 1].end, words[wi].start))
            prev_word_idx = wi

    char_times_per_sentence = []
    offset = 0
    for s in members:
        n = len(s["text"])
        char_times_per_sentence.append(char_times_flat[offset:offset + n])
        offset += n

    return split_times, char_times_per_sentence, edge_start, edge_end


def main():
    audio_path = sys.argv[1]
    in_enriched_path = sys.argv[2]
    out_enriched_path = sys.argv[3]

    enriched = json.load(open(in_enriched_path, encoding="utf-8"))
    sentences = enriched["sentences"]

    groups = {}
    for s in sentences:
        groups.setdefault((s["mondai"], s["question"]), []).append(s)

    multi_count = sum(1 for v in groups.values() if len(v) > 1)
    print(f"{len(groups)} questions total, {multi_count} have multiple sentences to refine boundaries; "
          f"all of them get char-level timing for word-highlight playback")

    model = WhisperModel("medium", device="cpu", compute_type="int8")
    clip_path = "refine_clip_tmp.wav"

    fixed, fallback_count, timed, timed_fallback = 0, 0, 0, 0
    for (mondai, question), members in groups.items():
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
            print(f"  {mondai} {question} {span_start}-{span_end}: only {len(words)} words for {n} sentences, "
                  f"skip boundary refine + word timing")
            continue

        split_times, char_times_per_sentence, edge_start, edge_end = align_group(members, words, span_start)
        method = "alignment"
        if edge_start is None:
            # 对齐失败（覆盖率太低）——外边界没有可信依据重新定位，保持原样；
            # 多句题目的内部切分退回字数比例，不强行相信一个烂对齐。
            edge_start, edge_end = 0.0, span_end - span_start
            if n > 1:
                split_times = proportional_split(members, words)
                method = "proportional-fallback"
                fallback_count += 1

        bounds = [edge_start] + (split_times or []) + [edge_end]
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

        if char_times_per_sentence is None:
            # 对齐质量不够，逐字符时间戳退回线性插值（在句子自己的 start/end 之间
            # 按字符位置比例估一个时间，不追求精确，只求高亮的移动方向不出错）。
            char_times_per_sentence = []
            for s in members:
                dur = s["end"] - s["start"]
                m = max(len(s["text"]), 1)
                char_times_per_sentence.append(
                    [round(s["start"] + dur * j / m, 2) for j in range(len(s["text"]))]
                )
            timed_fallback += 1
        for s, ct in zip(members, char_times_per_sentence):
            s["char_times"] = ct
            timed += 1

    sentences.sort(key=lambda s: s["start"])
    for i, s in enumerate(sentences, 1):
        s["id"] = i

    json.dump(enriched, open(out_enriched_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Refined {fixed} sentence boundaries ({fallback_count} questions used proportional fallback), "
          f"left {len(sentences) - fixed} untouched; computed word-highlight timing for {timed} sentences "
          f"({timed_fallback} questions used linear-interpolation fallback), wrote {out_enriched_path}")


if __name__ == "__main__":
    main()
