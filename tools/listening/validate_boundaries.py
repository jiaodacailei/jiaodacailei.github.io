# -*- coding: utf-8 -*-
"""
用法：python validate_boundaries.py <enriched.json> <输出 enriched.json> [--max-cps 25]

`refine_boundaries.py` 跑完之后必须做的收尾校验，之前每次都是现写一次性 python -c
片段，容易漏、也容易在不同次跑的时候写出不一致的检查逻辑——固化成脚本，每次跑法
完全一样：

  1. 按 mondai 分组、按 start 排序，相邻句如果前一句 end > 后一句 start 就前向裁剪
     （`a["end"] = b["start"]`），裁剪后重新检查一遍确认没有残留重叠
  2. 检查零时长/负时长句子（不修，直接报错退出——这种情况不该发生，出现了说明
     `refine_boundaries.py` 的对齐或兜底逻辑本身有 bug，需要回去看，不能悄悄吞掉）
  3. 按"字符数 / 时长"算一个粗略的语速指标，超过阈值的打印出来供人工复核——语速
     异常高（远超正常日语语速）往往是转写异常（比如 Whisper 复读循环导致对齐失败、
     切出了一堆近零时长句子）的信号，比等用户听出来更早发现问题
  4. 重新分配连续的 id，写出最终文件

裁剪、零时长检查、语速异常扫描这三步做完没发现问题，才算真正准备好进入
`build_page.py`。
"""
import sys
import json
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("in_enriched_json")
    ap.add_argument("out_enriched_json")
    ap.add_argument("--max-cps", type=float, default=25.0,
                     help="字符数/时长超过这个值就当异常打印出来（默认 25，正常日语语速一般在 5~10 字/秒）")
    args = ap.parse_args()

    with open(args.in_enriched_json, encoding="utf-8") as f:
        data = json.load(f)
    sentences = data["sentences"]
    sentences.sort(key=lambda s: s["start"])

    trimmed = 0
    for i in range(len(sentences) - 1):
        a, b = sentences[i], sentences[i + 1]
        if a["mondai"] == b["mondai"] and a["end"] > b["start"]:
            a["end"] = b["start"]
            trimmed += 1

    overlaps, bad_durations = [], []
    for i in range(len(sentences) - 1):
        a, b = sentences[i], sentences[i + 1]
        if a["mondai"] == b["mondai"] and a["end"] > b["start"]:
            overlaps.append((a["id"], b["id"]))
    for s in sentences:
        if s["end"] <= s["start"]:
            bad_durations.append(s["id"])

    if overlaps or bad_durations:
        print(f"FAIL: {len(overlaps)} residual overlaps after trim, {len(bad_durations)} zero/negative durations")
        for a, b in overlaps:
            print(f"  overlap: sentence {a} / {b}")
        for sid in bad_durations:
            print(f"  bad duration: sentence {sid}")
        print("这不该发生——说明 refine_boundaries.py 本身有 bug，不要在这里悄悄修掉，回去看对齐逻辑。")
        sys.exit(1)

    outliers = []
    for s in sentences:
        dur = s["end"] - s["start"]
        cps = len(s["text"]) / dur if dur > 0 else float("inf")
        if cps > args.max_cps:
            outliers.append((s["id"], round(s["start"], 2), round(s["end"], 2), round(cps, 1), s["text"][:30]))

    for i, s in enumerate(sentences, 1):
        s["id"] = i

    with open(args.out_enriched_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"OK: trimmed {trimmed} small overlaps, 0 remaining, wrote {args.out_enriched_json}")
    if outliers:
        print(f"WARNING: {len(outliers)} sentences with chars/sec > {args.max_cps}, likely bad cuts — 人工复核:")
        for sid, st, en, cps, text in outliers:
            print(f"  #{sid} {st}-{en} ({cps} chars/s): {text!r}")


if __name__ == "__main__":
    main()
