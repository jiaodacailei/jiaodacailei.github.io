# -*- coding: utf-8 -*-
"""
用法：
  python build_vocab_from_wordlist.py <vocab_words.json> <transcript.json> <输出enriched.json> \
      [--mondai 生词] [--drop-hallucination "幻觉原文1" --drop-hallucination "幻觉原文2" ...]

教材生词表专用（`jp-textbook-lesson` skill 用到）：把截图抄下来的 ground-truth
词表，跟 `transcribe.py` 对生词朗读音频的粗转写结果按顺序一一对应，生成
`build_page.py` 能直接吃的 `enriched.json`。**不跑 `refine_boundaries.py`**——
单词粒度的逐字符跟读高亮价值很低，直接用 Whisper 的粗 segment 时间戳就够用。

<vocab_words.json> 格式：
  [{"group": "生词表1", "text": "観光地", "zh": "[名] 观光胜地，旅游胜地", "kana": "かんこうち"}, ...]
  - "group"：这一条属于教材自己的哪个分组（照抄源材料的标签，比如"生词表1"），
    对应页面里的小题/侧栏导航。
  - "text"：喂给 `ruby_html()` 生成假名注音的原文——有汉字就填汉字形式（比如
    "観光地"），纯假名/片假名词条原样填（比如"スケジュール"）。
  - "zh"：中文释义，连词性标签一起抄（比如"[名] 观光胜地，旅游胜地"）方便记忆。
  - "kana"（可选，但强烈建议给每个有汉字的词条都填）：这个词条正确的假名读音。
    pykakasi 是按单字/常见复合词猜读音的，遇到熟字训/不规则读音的词容易猜错
    （比如"女将"会被猜成"じょしょう"，正确读音是"おかみ"）——填了这个字段
    就直接用这个读音包一层 `<ruby>`，不再让 pykakasi 自动转换。

跑完之后**务必再跑一遍 `validate_boundaries.py`**（即使这里没跑 `refine_
boundaries.py`）——`transcribe.py` 分块转写在块边界上偶尔会切出时间戳互相
重叠的相邻 segment，不清理的话前一个词的音频尾巴会多播出后一个词的开头。
`validate_boundaries.py` 的重叠裁剪不依赖 `refine_boundaries.py` 有没有跑过：

  python validate_boundaries.py <这个脚本的输出> <最终输出>

**这个脚本假设"词表按顺序 1:1 对应 segment"**，如果截图漏拍了某个词、或者
Whisper 把两个词的音频粘连转写成了一个 segment（真实案例：一个 segment 长达
7秒，明显长于同类词条的1~3秒，一查发现是漏拍的词跟下一个词粘连在一起被
当成了一个 segment），这里会直接对不上、或者数量对得上但内容从某个位置开始
错位——**总数相等不代表顺序/内容都对**，跑完之后建议打印一份"词表 vs
segment 文本"的逐位置对照表人工过一遍确认，尤其是留意时长明显偏长的
segment（很可能是粘连了不止一个词的音频，需要针对那个位置重新做一次
word-level 转写核实、手动拆开时间戳，这个脚本本身不处理这种情况）。

**时长本身正常也不代表内容对得上**——真实案例（textbook-sjp-zg-l10，用户
听出来的问题）：ビタミン/立て直す/体重/相当/天才 这5个词条最终对应到的
音频，时长都在正常范围（1~2秒，不像"粘连"那样异常偏长），但内容其实是
错的（体重对应的 segment 识别文本是"20"、相当是空字符串、天才是"はい"，
都是错位到了别的位置）——纯靠"时长是否异常"这一条完全抓不出这类错位。
脚本现在会自动把每个 segment 的识别文本转成假名读音、跟词条的读音（`kana`
字段，没有就用 `word["text"]` 走 `pykakasi` 转出来的读音）比一下相似度，
读音差得远的位置会打印出来提醒复核——按读音比而不是按字面比，是因为"社内
被听成车内""〜氏被听成死"这类同音异字是识别噪声里的正常情况，不该被当成
错位（这两种情况读音其实完全一样，按读音比就不会被误报）。这是提醒复核，
不是硬失败——识别本身偶尔会有噪声导致相似度算出来偏低，但确实是对的，
打印出来的位置需要人工判断，不能不看内容就当成真的错了，也不能因为脚本
没跑出警告就不管别的位置了（这条检查跟"留意时长异常"一样，只是缩小人工
复核范围的辅助信号，不是万能的正确性保证）。
"""
import sys
import os
import re
import json
import argparse
import difflib
import pykakasi

sys.path.insert(0, os.path.dirname(__file__))
from build_page import ruby_html, _is_kanji, _split_trailing_kana

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_kks = pykakasi.kakasi()
_PUNCT_RE = re.compile(r"[\s　、。，,．.!?！？「」『』()（）:：;；~〜・…\-—―'\"０-９0-9]")


def to_hiragana(text):
    text = _PUNCT_RE.sub("", text or "")
    return "".join(t["hira"] for t in _kks.convert(text))


def reading_of(word):
    return to_hiragana(word["kana"]) if "kana" in word else to_hiragana(word["text"])


def furigana_for(word):
    if "kana" in word:
        text, kana = word["text"], word["kana"]
        # 送假名（比如"比べ"的"べ"）不能连着汉字一起包进 <ruby>——那样注音会
        # 显示成"くらべ"整个盖住"比べ"两个字，正确排版是只给汉字本体"比"注
        # "くら"，"べ"本来就是假名，照原样显示在 <ruby> 外面，不用再注一遍。
        # 跟 build_page.py 的 tokenize_ja() 处理自动分词结果时用的是同一条
        # 规则（同一个 _split_trailing_kana()），`kana` 覆盖分支不能因为跳过
        # 了自动分词就漏掉这一步。
        if any(_is_kanji(ch) for ch in text) and kana != text:
            core_orig, core_hira, suffix = _split_trailing_kana(text, kana)
            return f'<ruby>{core_orig}<rt>{core_hira}</rt></ruby>{suffix}'
        return text
    return ruby_html(word["text"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vocab_words_json")
    ap.add_argument("transcript_json")
    ap.add_argument("out_json")
    ap.add_argument("--mondai", default="生词", help="统一填的 mondai 标签（默认“生词”）")
    ap.add_argument("--drop-hallucination", action="append", default=[],
                     help="要从 segment 里剔除的 Whisper 幻觉原文，可重复传多个")
    ap.add_argument("--mismatch-threshold", type=float, default=0.5,
                     help="词条读音跟 segment 识别读音的相似度（0~1，difflib ratio）低于"
                          "这个值就打印警告提醒人工复核，默认0.5，不需要频繁调")
    args = ap.parse_args()

    words = json.load(open(args.vocab_words_json, encoding="utf-8"))
    transcript = json.load(open(args.transcript_json, encoding="utf-8"))
    segments = [s for s in transcript["segments"] if s["text"] not in args.drop_hallucination]

    if len(segments) != len(words):
        print(f"FAIL: 词表有 {len(words)} 条，segment 有 {len(segments)} 个，数量对不上。")
        print("先检查是不是漏了 --drop-hallucination、或者截图/转写哪边少了/多了内容，不要强行截断对应。")
        sys.exit(1)

    sentences = []
    mismatches = []
    for i, (w, seg) in enumerate(zip(words, segments), start=1):
        expected = reading_of(w)
        actual = to_hiragana(seg["text"])
        ratio = difflib.SequenceMatcher(None, expected, actual).ratio() if expected and actual else 0.0
        if ratio < args.mismatch_threshold:
            mismatches.append((i, w["text"], expected, seg["text"], actual, ratio))
        sentences.append({
            "id": i,
            "mondai": args.mondai,
            "question": w["group"],
            "start": seg["start"],
            "end": seg["end"],
            "text": w["text"],
            "furigana": furigana_for(w),
            # data-driven 页面（build_page.py --data-driven）不用 furigana 这个
            # 预先拼好的 HTML 字符串，而是要 token 级的数据——生词条目没有
            # char_times（单词粒度不做逐字符跟读高亮），sentence_to_data() 拿不到
            # 词级时间戳来跑 tokenize_ja()，只能整词当一个 token 处理，这时候
            # word 自己填的 kana 覆盖读音就得原样传下去，不能丢在这一步。
            "kana": w.get("kana"),
            "zh": w["zh"],
            "notes": "",
            "char_times": None,
        })

    json.dump({"sentences": sentences, "questions": []},
              open(args.out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"wrote {len(sentences)} vocab sentences to {args.out_json}")
    print("别忘了再跑一遍 validate_boundaries.py 清理重叠时间戳。")
    if mismatches:
        print(f"\nWARNING: {len(mismatches)} 处词条读音跟 segment 识别读音差得较远，"
              f"人工复核一下这几个位置（不代表一定错，识别噪声也可能触发，但值得看一眼）：")
        for i, text, expected, seg_text, actual, ratio in mismatches:
            print(f"  #{i} {text!r} 期望读音 {expected!r} vs segment原文 {seg_text!r}"
                  f"（读音 {actual!r}），相似度 {ratio:.2f}")


if __name__ == "__main__":
    main()
