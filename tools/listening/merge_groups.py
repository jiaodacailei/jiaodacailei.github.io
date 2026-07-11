# -*- coding: utf-8 -*-
"""
用法：python merge_groups.py <raw_sentences.json> <输出 enriched.json> <分组结果1.json> [分组结果2.json ...]

给结构化听力材料（比如 JLPT 真题，按大题/小题分好了边界）用的合并脚本，
配合"多个 Agent 并行做逐句拆分+翻译"的流程使用：

  1. 先准备 raw_sentences.json：数组，每项是原始转写的一个片段
     {"raw_id": 1, "mondai": "問題1", "question": "1番", "start": 117.64, "end": 126.64, "text": ".."}
  2. 把 raw_sentences.json 按 mondai 拆成几份，分给多个 Agent 并行处理，每个 Agent
     参考"已校对过的整题文本"把内容拆成自然的句子，并把每句话对应的 raw_id 标注出来
     （因为原始转写经常把一句话切成两段、或者把两句话粘一起，需要 Agent 判断合并）。
     每个 Agent 返回一个 JSON 对象：
     {
       "sentences": [{"raw_ids": [1,2], "question": "1番", "text": "..", "zh": "..", "notes": ".."}, ...],
       "questions": [{"question": "1番", "overview": "..", "answer": ".."}, ...]
     }
  3. 把每个 Agent 的结果各自存成一个 json 文件，用本脚本合并：
     - 用 raw_ids 反查 raw_sentences.json 得到 start（取最早）/end（取最晚）/mondai
     - 自动生成假名注音（<ruby>）
     - 按 start 时间排序，重新分配全局 id
     - questions 数组按 mondai + 原始顺序合并去重
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
    raw_path = sys.argv[1]
    out_path = sys.argv[2]
    result_paths = sys.argv[3:]

    with open(raw_path, encoding="utf-8") as f:
        raw_list = json.load(f)
    raw_by_id = {r["raw_id"]: r for r in raw_list}

    sentences = []
    questions = []
    seen_questions = set()

    for rp in result_paths:
        with open(rp, encoding="utf-8") as f:
            result = json.load(f)

        for s in result.get("sentences", []):
            raws = [raw_by_id[rid] for rid in s["raw_ids"] if rid in raw_by_id]
            if not raws:
                continue
            start = min(r["start"] for r in raws)
            end = max(r["end"] for r in raws)
            mondai = raws[0]["mondai"]
            sentences.append({
                "mondai": mondai,
                "question": s["question"],
                "start": start,
                "end": end,
                "text": s["text"],
                "furigana": to_ruby_html(s["text"]),
                "zh": s["zh"],
                "notes": s.get("notes", ""),
            })

        for q in result.get("questions", []):
            # infer mondai from any sentence in this same result file with matching question
            mondai = None
            for s in result.get("sentences", []):
                if s["question"] == q["question"]:
                    raws = [raw_by_id[rid] for rid in s["raw_ids"] if rid in raw_by_id]
                    if raws:
                        mondai = raws[0]["mondai"]
                        break
            key = (mondai, q["question"])
            if key in seen_questions:
                continue
            seen_questions.add(key)
            questions.append({
                "mondai": mondai,
                "question": q["question"],
                "overview": q.get("overview", ""),
                "answer": q.get("answer", ""),
            })

    sentences.sort(key=lambda x: x["start"])
    for i, s in enumerate(sentences, 1):
        s["id"] = i

    # order questions by the start time of their first sentence
    first_start = {}
    for s in sentences:
        key = (s["mondai"], s["question"])
        if key not in first_start:
            first_start[key] = s["start"]
    questions.sort(key=lambda q: first_start.get((q["mondai"], q["question"]), 1e18))

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"sentences": sentences, "questions": questions}, f, ensure_ascii=False, indent=2)

    print(f"Merged {len(sentences)} sentences and {len(questions)} questions from {len(result_paths)} files into {out_path}")


if __name__ == "__main__":
    main()
