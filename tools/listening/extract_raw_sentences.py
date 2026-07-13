# -*- coding: utf-8 -*-
"""
用法：
  python extract_raw_sentences.py <transcribe.py 输出的 transcript.json> <items.json> \
      <输出 raw_sentences.json> [--drop "ご視聴ありがとうございました" ...]

结构化流程第3步"中间步骤"用的工具：从原始转写 + `find_item_boundaries.py`（或人工手写）
产出的 items.json 边界，为每道小题提取时间范围内的原始 segments，删掉纯语气词/空片段，
得到 raw_sentences.json：数组，每项
`{"raw_id":.., "mondai":.., "question":.., "start":.., "end":.., "text": "原始转写"}`。
同时按 mondai 拆成 raw_m1.json ~ raw_mN.json（跟输出文件放同一目录），分别喂给下一轮的
逐句拆分 Agent。

这一步逻辑是纯机械的（按时间范围筛 segments + 过滤语气词），之前每次真实案例都是现写
一次性脚本做，三份几乎一模一样，现在固化成这一个可重跑的工具，不用再现写。

`--drop` 用来过滤 Whisper 幻觉出的、跟内容无关的整句（比如安静片段编出的
"ご視聴ありがとうございました"这类视频结尾语）——这个不像纯语气词那样有固定的封闭
集合，每份录音幻觉出的内容不一样，靠通读转写文本人工发现，用这个参数删，可重复传
多个，结果依然是命令行可重跑的，不用直接改 transcript.json。
"""
import os
import re
import sys
import json
import argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 纯语气词/独立感叹词——单独成一整个 segment 时不携带任何内容信息，删掉不影响后面
# 逐句拆分（如果语气词是句子内部的一部分，比如"あの、それは..."，会跟着所在 segment
# 的其它文字一起保留，这里只过滤"整个 segment 就只有语气词"的情况）。
FILLER_ONLY = {"ん", "うん", "あ", "ああ", "ああああああ", "え", "えっと"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript_path")
    ap.add_argument("items_path")
    ap.add_argument("out_path")
    ap.add_argument("--drop", action="append", default=[],
                     help="删掉整句等于这个文本的 segment（Whisper 幻觉句等），可重复传多个")
    args = ap.parse_args()

    transcript = json.load(open(args.transcript_path, encoding="utf-8"))
    items = json.load(open(args.items_path, encoding="utf-8"))
    segments = transcript["segments"]
    drop_set = set(args.drop)

    raw = []
    raw_id = 1
    for item in items:
        for seg in segments:
            if seg["start"] >= item["start"] and seg["end"] <= item["end"] + 0.01:
                text = seg["text"].strip()
                if not text or text in FILLER_ONLY or text in drop_set:
                    continue
                raw.append({
                    "raw_id": raw_id,
                    "mondai": item["mondai"],
                    "question": item["label"],
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": text,
                })
                raw_id += 1

    out_dir = os.path.dirname(os.path.abspath(args.out_path)) or "."
    json.dump(raw, open(args.out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    by_mondai = {}
    for r in raw:
        by_mondai.setdefault(r["mondai"], []).append(r)
    for mondai, rs in by_mondai.items():
        n = re.sub(r"\D", "", mondai) or mondai
        split_path = os.path.join(out_dir, f"raw_m{n}.json")
        json.dump(rs, open(split_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"{len(raw)} raw sentences extracted across {len(items)} items, {len(by_mondai)} mondai groups")
    for mondai, rs in sorted(by_mondai.items()):
        print(f"  {mondai}: {len(rs)} raw sentences")


if __name__ == "__main__":
    main()
