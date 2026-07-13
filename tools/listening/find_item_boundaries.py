# -*- coding: utf-8 -*-
"""
用法：python find_item_boundaries.py <transcribe.py 输出的 transcript.json> <输出 items.json>
      [--insert "問題2:4番:974.44" ...]

--insert 用来补漏检——有些标记 Whisper 会完全听漏、连裸数字的痕迹都不留（不是所有
漏检都能靠"断号检测"/"时长异常检测"自动定位到精确时间点，这两个检测只能告诉你
"問題2 缺第4号""問題5 第1小题时长异常"，具体该在哪个时间点插入还是要人工回去看
转写文本确认），确认好时间点后用这个参数补，可重复传多个，结果依然是完整命令行
可重跑的，不用手改输出的 json。

JLPT 型听力材料（"問題1""1番""2番"…这类口播编号分段）自动识别每道小题的时间边界，
替代之前"通读转写文本、手写一次性脚本标时间戳"的人工步骤——这套编号规律是固定的，
没必要每次都靠人工读一遍。

识别逻辑：
  1. 找每个"問題N"大题的口播位置（大题标题+复述都会命中，取第一次出现的时间当这个
     大题的起点参考）。
  2. 每个大题范围内看有没有"練習"提示（practice cue）——問題1~4 通常有说明+练习
     例题，例题讲完会用"では始めます"开启正式内容，练习例题本身不算小题，必须跳过；
     問題5 一般没有练习（口播原文是"この問題には練習はありません"）。判断"有没有
     练习"不能简单认"練習"这两个字出现过——問題5 的"練習はありません"本身也含这
     两个字，所以用"練習(?!はありません)"排除掉这句；同时也不能死认死"では練習
     しましょう"这个精确措辞，真实转写里这句被 Whisper 听成过"では練習しません"
     （"しましょう"/"しません"这种小词尾巴转写本来就不稳定），只要"練習"后面跟的
     不是"はありません"就当有练习。這種"没有练习"的情況下小题编号本身就在说明
     文字里最先出现，不需要跳过任何东西，从大题起点直接扫描即可。
  3. 确定好"从哪开始扫描"之后，找小题编号标记"N番"（阿拉伯数字/全角数字/汉数字都
     认，"五番"这种也算）。每个标记的时间戳就是这道小题的起点，下一个标记（或下一
     个大题的起点、或录音结尾）就是这道小题的终点上限。**"質問1""質問2"这种（問題5
     第二种子问题格式）不当成独立小题的起点**——它们是同一道"N番"内部的两个提问，
     跟"N番"本身不是同一层级，切分到这个粒度交给后面 `refine_boundaries.py`
     的题目内部精修去做，这里只标最外层的"N番"边界。
  4. 小题终点直接取"下一个标记的起点"，不用抠得多精确——这一步产出的 items.json
     只是给 raw_sentences 提取用的粗边界，真正精确到句子级的边界由后面的
     `refine_boundaries.py` 重新对齐，这里差个一两秒不影响最终结果，但**不能**
     把下一个大题的说明口播("問題2ではまず…")混进上一个大题最后一小题的范围里——
     这是之前踩过的坑，所以终点始终以下一个已识别到的标记为准，不额外外推。

**这是识别辅助，不是全自动免检**：跑完打印出每道小题识别到的编号+时间戳，一定要
过一遍确认编号连续、没有漏检/误检（比如选项里念到的数字被误认成小题编号），再拿去
下一步。常见误检来源：问题里如果读到选项"1""2""3"且后面紧跟"番"字的谐音词，或者
对话内容本身提到"N番线"之类跟"番"同形的词——多留意打印出来的上下文文本。
"""
import re
import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MONDAI_RE = re.compile(r'問題\s*([1-5１２３４５])')
START_MARK_RE = re.compile(r'では(始め|はじめ)ます')
PRACTICE_CUE_RE = re.compile(r'練習(?!はありません)')
KANJI_NUM = "一二三四五六七八九十"
# 「一番」是极常见的日常词（"最……"的意思，比如"一番いい場所"），不是小题编号的
# 概率远高于是的概率——真实案例里一份录音出现4次"一番"，没有一次是小题标记。
# 单独的"一"排除在小题编号的汉数字匹配之外（"二""三"...等其它汉数字日常用法里
# 加"番"的搭配少得多，风险低很多，继续认）。第1小题不靠这个正则识别，靠下面
# "从内容起点隐式当作1番"来兜底，不依赖"1番"/"一番"这个文本标记真的被念出来
# ——真实案例也出现过第1小题编号整个没有被念/被听漏的情况。
KANJI_NUM_FOR_ITEM = "二三四五六七八九十"
ITEM_RE = re.compile(
    r'(?:^|[^0-9０-９一二三四五六七八九十])'
    r'([0-9０-９]{1,2}|[' + KANJI_NUM_FOR_ITEM + r']{1,3})'
    r'番(?!線|目)'
)

FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
KANJI_DIGIT_MAP = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
                    "八": 8, "九": 9, "十": 10}


def normalize_number(raw):
    raw = raw.translate(FULLWIDTH_DIGITS)
    if raw.isdigit():
        return int(raw)
    if raw in KANJI_DIGIT_MAP:
        return KANJI_DIGIT_MAP[raw]
    # 十几的汉数字（十一~十五在番号里基本不会出现，但保险起见处理一下）
    if raw.startswith("十") and len(raw) > 1 and raw[1] in KANJI_DIGIT_MAP:
        return 10 + KANJI_DIGIT_MAP[raw[1]]
    return None


def parse_insert(spec):
    """--insert 的参数格式："問題2:4番:974.44"——手动指定某个大题下漏检的小题标记
    该插在哪个时间点。漏检不是每次都能自动补（比如整句编号被 Whisper 完全听漏，
    连裸数字的痕迹都没留下），这种情况下人工回去核对转写文本、确定好时间点之后，
    用这个参数把结果也变成命令行可重跑的一部分，不是直接手改输出的 json。"""
    mondai, label, t = spec.split(":")
    return mondai, label, float(t)


def detect_renumber_bounds(segments, start_mondai, force_splits=()):
    """没有「問題N」播报标记时的兜底（真实案例：2020年12月N2录音，分享者把播音员的
    说明/编号播报整段剪掉了，但内容其实还是结构化的5道大题）。没有"問題N"这个锚点，
    只能靠"N番"这类小题编号本身的规律反推大题分界：JLPT 每道大题内部小题编号从1
    连续数到底，编号又从1重新数起的地方，就是新大题的开始。跟明确有"問題N"标记时
    一样，这也只是粗边界，不追求精确到秒——真正的小题内容边界交给 refine_boundaries.py
    重新对齐，这里的分界只要能把"1番"这类真正的小题标记扫描起点圈对就够用。

    返回 {mondai数字: (lo, hi)}，跟 mondai_starts 场景下 mondai_bounds 的形状一致，
    后面的大题内小题扫描逻辑不用关心边界是从哪种方式来的。识别不到任何"N番"编号
    （连这个规律都用不上，说明内容压根不是结构化材料）时返回 None，调用方应该退回
    SKILL.md 的"简单流程"。"""
    markers = []
    for seg in segments:
        im = ITEM_RE.search(seg["text"])
        if im:
            n = normalize_number(im.group(1))
            if n:
                markers.append((seg["start"], n))
    if not markers:
        return None

    groups = []
    current = []
    last_num = None
    for t, n in markers:
        if n == 1 and last_num is not None and last_num != 1:
            groups.append(current)
            current = []
        current.append((t, n))
        last_num = n
    groups.append(current)

    interval_bounds = []
    prev_hi = segments[0]["start"]
    for i, g in enumerate(groups):
        hi = groups[i + 1][0][0] if i + 1 < len(groups) else segments[-1]["end"]
        interval_bounds.append((prev_hi, hi))
        prev_hi = hi

    # --force-split 补丁：编号重置规律只在"新大题的第一小题真的被听成1番"时才触发，
    # 如果这道小题的编号被 Whisper 完全听漏/听成裸数字（比如这道小题干脆没留下任何
    # "N番"文本痕迹），规律本身就失灵，两个大题会被错误合并成一段——这种情况规律
    # 本身补不出缺的分界点，只能人工核对转写文本确定时间点后用这个参数强制拆开
    # （跟 --insert 是同一个思路：弱信号推断有极限，缺口交给人工＋命令行参数补，
    # 不是手改输出的 json）。
    if force_splits:
        split_points = []
        for lo, hi in interval_bounds:
            pts = sorted(t for t in force_splits if lo < t < hi)
            prev = lo
            for t in pts:
                split_points.append((prev, t))
                prev = t
            split_points.append((prev, hi))
        interval_bounds = split_points

    bounds = {}
    for i, (lo, hi) in enumerate(interval_bounds):
        bounds[start_mondai + i] = (lo, hi)
    print(f"没有识别到「問題N」播报标记，退回按「番」编号从1重新计数的规律推断大题"
          f"分界——识别到 {len(groups)} 段编号序列"
          + (f"，force-split 后拆成 {len(interval_bounds)} 段" if force_splits else "")
          + f"，按 問題{start_mondai}~問題{start_mondai + len(interval_bounds) - 1} "
          f"顺序假设（--start-mondai 可改起始号）。这是弱信号推断，务必核对大题数量、"
          f"顺序是否符合预期，尤其留意播音员说明/练习例题是否也被剪掉——剪掉了的话不"
          f"影响这里的分界，剪不干净留了残留文本就可能干扰下面的练习提示检测。如果某道"
          f"大题的第一小题编号被听漏/听成裸数字、规律因此把它跟前一个大题错误合并了，"
          f"用 --force-split <时间戳> 人工指定分界点（可重复传多个）。")
    return bounds


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript_path")
    ap.add_argument("out_path")
    ap.add_argument("--insert", action="append", default=[],
                     help='手动补一个漏检的小题标记，格式 "問題2:4番:974.44"，可重复传多个')
    ap.add_argument("--start-mondai", type=int, default=1,
                     help="没有「問題N」标记、退回按「番」编号重新计数推断大题分界时，"
                          "第一段编号序列算第几大题（默认1；如果問題1整段被剪掉、"
                          "录音从問題2开始，传2）")
    ap.add_argument("--force-split", action="append", type=float, default=[],
                     help="没有「問題N」标记的兜底模式下，某道大题的第一小题编号被"
                          "听漏/听成裸数字导致规律没能拆出它自己的分界时，人工指定"
                          "分界时间戳强制拆开（可重复传多个，仅对兜底模式生效）")
    args = ap.parse_args()
    transcript_path, out_path = args.transcript_path, args.out_path
    manual_inserts = [parse_insert(s) for s in args.insert]
    segments = json.load(open(transcript_path, encoding="utf-8"))["segments"]

    mondai_starts = {}  # mondai数字 -> 第一次出现的时间
    for seg in segments:
        m = MONDAI_RE.search(seg["text"])
        if m:
            n = normalize_number(m.group(1))
            if n and n not in mondai_starts:
                mondai_starts[n] = seg["start"]

    if mondai_starts:
        mondai_order = sorted(mondai_starts)
        mondai_bounds = {}
        for i, n in enumerate(mondai_order):
            next_start = mondai_starts[mondai_order[i + 1]] if i + 1 < len(mondai_order) else segments[-1]["end"]
            mondai_bounds[n] = (mondai_starts[n], next_start)
    else:
        mondai_bounds = detect_renumber_bounds(segments, args.start_mondai, args.force_split)
        if mondai_bounds is None:
            print("没有识别到任何「問題N」标记，也没有识别到任何「N番」编号——这份材料"
                  "可能不是结构化的 JLPT 型内容，应该走 SKILL.md 里的「简单流程」，"
                  "不需要 items.json。")
            sys.exit(1)
        mondai_order = sorted(mondai_bounds)

    items = []
    for n in mondai_order:
        lo, hi = mondai_bounds[n]
        in_range = [seg for seg in segments if lo <= seg["start"] < hi]

        has_practice = any(PRACTICE_CUE_RE.search(seg["text"]) for seg in in_range)
        content_start = lo
        if has_practice:
            start_mark_time = None
            for seg in in_range:
                if START_MARK_RE.search(seg["text"]):
                    start_mark_time = seg["end"]
            if start_mark_time is not None:
                content_start = start_mark_time
            else:
                print(f"  警告：問題{n} 检测到练习提示（練習しましょう）但没找到"
                      f"「では始めます」，跳不过练习例题，边界可能会把例题的答案揭晓"
                      f"（比如「最も良いものは3番です」）误判成小题标记，重点核对。")

        markers = []  # (time, label)
        for seg in in_range:
            if seg["start"] < content_start:
                continue
            im = ITEM_RE.search(seg["text"])
            if im:
                inum = normalize_number(im.group(1))
                if inum:
                    markers.append((seg["start"], f"{inum}番"))
        for m_mondai, m_label, m_t in manual_inserts:
            if m_mondai == f"問題{n}":
                markers.append((m_t, m_label))
                print(f"  手动补：{m_mondai} {m_label} @ {m_t:.2f}")
        markers.sort(key=lambda x: x[0])  # 手动插入的标记可能打乱了原本的时间顺序，重新排一遍

        # 第1小题不靠文本标记识别，直接把"内容起点"当成隐式的1番——第1小题的编号
        # 有时候压根没被念出来/被 Whisper 听漏（真实案例：問題5 1番），与其依赖一个
        # 可能不存在的文本标记，不如直接用结构性事实（内容起点＝第1小题起点）。
        # 这也顺带避免了"一番"这个日常词被误判成1番标记的问题——预置进 seen 之后，
        # 后面文本里出现的"一番"/"1番"都会被下面的去重逻辑当成重复标记滤掉。
        seen = {"1番"}
        dedup_markers = [(content_start, "1番")]
        for t, label in markers:
            if label in seen:
                continue
            seen.add(label)
            dedup_markers.append((t, label))

        # 隐式1番是个"这道题起点必然有内容"的假设——如果这道题的起点（content_start）
        # 跟紧接着的第一个真实标记时间戳重合（没有间隔），说明起点这里根本没有独立于
        # 第一个真实标记的内容，隐式1番就是个零时长的幽灵条目，删掉，让第一个真实标记
        # 自己的编号（可能不是"1番"，比如力度拆分正好切在下一题第一个真实标记上）
        # 当这道题真正的第一条。
        if len(dedup_markers) >= 2 and dedup_markers[1][0] <= dedup_markers[0][0]:
            dedup_markers.pop(0)

        # 编号应该是从1连续数到N的——缺号八成是 Whisper 把"N番"听漏/听成了裸数字
        # （真实案例都出现过：整句漏听、或者"番"字单独丢字），不是"这道题真的不存在"。
        # 自动补不出来（不知道该在哪个时间点插入），但要把缺口明确点出来，不能让人
        # 靠肉眼一行行数有没有断号。
        found_nums = set()
        for _, label in dedup_markers:
            mnum = re.match(r'(\d+)番', label)
            if mnum:
                found_nums.add(int(mnum.group(1)))
        if found_nums:
            expected_max = max(found_nums)
            missing = sorted(set(range(1, expected_max + 1)) - found_nums)
            if missing:
                print(f"  警告：問題{n} 编号不连续，缺失 {missing}（识别到 {sorted(found_nums)}）——"
                      f"大概率是 Whisper 把对应的「N番」听漏或听成了裸数字，需要人工回去核对"
                      f"转写文本、手动补上缺失的边界，不要直接当成'这道题不存在'跳过。")

        mondai_items = []
        for i, (t, label) in enumerate(dedup_markers):
            end = dedup_markers[i + 1][0] if i + 1 < len(dedup_markers) else hi
            mondai_items.append({"mondai": f"問題{n}", "label": label, "start": round(t, 2), "end": round(end, 2)})

        # 断号检测只能抓"中间漏了一个号"，抓不到"最后一个号整句被听漏"（比如問題5
        # 只剩"1番"、真正的"2番"连痕迹都没留下）——这种情况下号码本身是"连续"的
        # （1..1 没有缺口），唯一露出马脚的地方是这道小题的时长离谱地长。用同一个
        # 大题内其它小题的中位时长当参照，超过 2.5 倍或绝对值超过90秒就打印出来，
        # 大概率是内部吞了至少一个没检测到的小题。
        if len(mondai_items) >= 1:
            durations = [it["end"] - it["start"] for it in mondai_items]
            durations_sorted = sorted(durations)
            median_dur = durations_sorted[len(durations_sorted) // 2]
            for it, dur in zip(mondai_items, durations):
                if dur > 90 and (len(mondai_items) == 1 or dur > 2.5 * median_dur):
                    print(f"  警告：{it['mondai']} {it['label']} 时长 {dur:.1f}秒，"
                          f"明显比同大题其它小题长（中位数 {median_dur:.1f}秒）——很可能内部"
                          f"吞了至少一道没被识别到的小题（比如整句「N番」被 Whisper 完全听漏，"
                          f"不是听成裸数字那种还留了点痕迹的漏检），需要人工回去听/读这段范围。")

        items.extend(mondai_items)

    for i, it in enumerate(items, 1):
        it["id"] = i

    for it in items:
        print(f"  #{it['id']:>3} {it['mondai']} {it['label']:>6}  {it['start']:>8.2f} - {it['end']:>8.2f}")
    print(f"共识别到 {len(items)} 道小题，{len(mondai_order)} 个大题。"
          f"务必核对编号是否连续、有没有漏检/误检再进入下一步。")

    json.dump(items, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
