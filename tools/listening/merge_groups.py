# -*- coding: utf-8 -*-
"""
用法：python merge_groups.py <items.json> <output enriched.json> <result1.json> [result2.json ...]

给结构化听力材料（比如 JLPT 真题，按大题/小题分好了边界）用的合并脚本，
配合"多个 Agent 并行翻译不同分组"的流程使用：

  1. 先手动或半自动整理出 items.json：数组，每项至少有
     {"id": 1, "group": "問題1", "label": "1番", "start": 117.64, "end": 201.72}
     （group/label 用于分组小标题和卡片编号，start/end 用于切音频）
  2. 把 items 按 group 分给多个 Agent 并行处理，每个 Agent 返回一个 JSON 数组，
     每项 {"id":.., "label":.., "text": "清理后的日语原文", "zh": "中文翻译",
           "notes": "语法笔记", "answer": "答案(可选)"}
  3. 把每个 Agent 的结果各自存成一个 json 文件，用本脚本合并：
     - 按 id 对齐 items.json 里的 group/start/end
     - 自动生成假名注音（<ruby>）
     - 按 id 排序输出成 enriched.json
  4. enriched.json 直接喂给 build_page.py 生成最终页面。

注意：Agent 返回的 JSON 里如果中文字段用了英文直引号 " 做强调，
直接嵌进 JSON 字符串会导致解析失败——写文件前请自查/替换成「」或中文弯引号。
"""
import sys
import json
import pykakasi

kks = pykakasi.kakasi()


def is_kanji(ch):
    return '一' <= ch <= '鿿'


def to_ruby_html(text):
    lines = text.split("\n")
    out_lines = []
    for line in lines:
        tokens = kks.convert(line)
        parts = []
        for t in tokens:
            orig = t['orig']
            hira = t['hira']
            if any(is_kanji(ch) for ch in orig) and hira != orig:
                parts.append(f'<ruby>{orig}<rt>{hira}</rt></ruby>')
            else:
                parts.append(orig)
        out_lines.append(''.join(parts))
    return '<br>'.join(out_lines)


def main():
    items_path = sys.argv[1]
    out_path = sys.argv[2]
    result_paths = sys.argv[3:]

    with open(items_path, encoding="utf-8") as f:
        items = json.load(f)
    by_id = {it["id"]: it for it in items}

    merged = []
    for rp in result_paths:
        with open(rp, encoding="utf-8") as f:
            results = json.load(f)
        for r in results:
            base = by_id[r["id"]]
            merged.append({
                "id": r["id"],
                "group": base.get("group"),
                "label": r.get("label", base.get("label", "")),
                "start": base["start"],
                "end": base["end"],
                "text": r["text"],
                "furigana": to_ruby_html(r["text"]),
                "zh": r["zh"],
                "notes": r["notes"],
                "answer": r.get("answer", ""),
            })

    merged.sort(key=lambda x: x["id"])

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"Merged {len(merged)} items from {len(result_paths)} files into {out_path}")


if __name__ == "__main__":
    main()
