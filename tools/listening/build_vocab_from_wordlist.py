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
"""
import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(__file__))
from build_page import ruby_html

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def furigana_for(word):
    if "kana" in word:
        return f'<ruby>{word["text"]}<rt>{word["kana"]}</rt></ruby>'
    return ruby_html(word["text"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vocab_words_json")
    ap.add_argument("transcript_json")
    ap.add_argument("out_json")
    ap.add_argument("--mondai", default="生词", help="统一填的 mondai 标签（默认“生词”）")
    ap.add_argument("--drop-hallucination", action="append", default=[],
                     help="要从 segment 里剔除的 Whisper 幻觉原文，可重复传多个")
    args = ap.parse_args()

    words = json.load(open(args.vocab_words_json, encoding="utf-8"))
    transcript = json.load(open(args.transcript_json, encoding="utf-8"))
    segments = [s for s in transcript["segments"] if s["text"] not in args.drop_hallucination]

    if len(segments) != len(words):
        print(f"FAIL: 词表有 {len(words)} 条，segment 有 {len(segments)} 个，数量对不上。")
        print("先检查是不是漏了 --drop-hallucination、或者截图/转写哪边少了/多了内容，不要强行截断对应。")
        sys.exit(1)

    sentences = []
    for i, (w, seg) in enumerate(zip(words, segments), start=1):
        sentences.append({
            "id": i,
            "mondai": args.mondai,
            "question": w["group"],
            "start": seg["start"],
            "end": seg["end"],
            "text": w["text"],
            "furigana": furigana_for(w),
            "zh": w["zh"],
            "notes": "",
            "char_times": None,
        })

    json.dump({"sentences": sentences, "questions": []},
              open(args.out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"wrote {len(sentences)} vocab sentences to {args.out_json}")
    print("别忘了再跑一遍 validate_boundaries.py 清理重叠时间戳。")


if __name__ == "__main__":
    main()
