# -*- coding: utf-8 -*-
"""
用法：python add_furigana.py <筛选后的segments.json> <输出enriched.json>

输入是一个 JSON 数组，每项 {"start":..,"end":..,"text":".."}（从 transcribe.py
的输出里人工挑选、删减后得到，可选 "zh"/"notes"/"mondai"/"question" 字段）。
输出是 refine_boundaries.py/validate_boundaries.py/build_page.py 都能直接吃的
{"sentences":[...], "questions":[]} 格式：每句补上 id、假名注音 HTML（<ruby>），
zh/notes 留空待填，mondai/question 没传就统一给同一个占位值（让下游按
mondai+question 分组时，这批句子被归到同一组，build_page.py 渲染成扁平列表，
不会产生多个 tab/多层目录）。
"""
import sys
import json
import pykakasi

kks = pykakasi.kakasi()


def is_kanji(ch):
    return '一' <= ch <= '鿿'


def to_ruby_html(text):
    tokens = kks.convert(text)
    parts = []
    for t in tokens:
        orig = t['orig']
        hira = t['hira']
        if any(is_kanji(ch) for ch in orig) and hira != orig:
            parts.append(f'<ruby>{orig}<rt>{hira}</rt></ruby>')
        else:
            parts.append(orig)
    return ''.join(parts)


def main():
    in_path, out_path = sys.argv[1], sys.argv[2]
    with open(in_path, encoding='utf-8') as f:
        segments = json.load(f)

    for i, seg in enumerate(segments, 1):
        seg['id'] = i
        seg['furigana'] = to_ruby_html(seg['text'])
        seg.setdefault('zh', "")
        seg.setdefault('notes', "")
        seg.setdefault('mondai', "听力材料")
        seg.setdefault('question', "")

    out = {"sentences": segments, "questions": []}
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(segments)} segments to {out_path}")
    print("下一步：填写每条的 zh（中文翻译）和 notes（语法/发音笔记）字段，"
          "有需要的话给互不相邻的句子分配不同的 question 值防止 refine_boundaries.py "
          "把它们当连续对话整体对齐，再跑 refine_boundaries.py/validate_boundaries.py/build_page.py")


if __name__ == "__main__":
    main()
