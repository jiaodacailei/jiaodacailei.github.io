# -*- coding: utf-8 -*-
"""
用法：python add_furigana.py <筛选后的segments.json> <输出enriched.json>

输入是一个 JSON 数组，每项 {"start":..,"end":..,"text":".."}（从 transcribe.py
的输出里人工挑选、删减后得到）。输出会补上 id、假名注音 HTML（<ruby>），
并预留空的 zh（中文翻译）、notes（语法/发音笔记）字段等待人工/AI 填写。
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

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(segments)} segments to {out_path}")
    print("下一步：填写每条的 zh（中文翻译）和 notes（语法/发音笔记）字段，再跑 build_page.py")


if __name__ == "__main__":
    main()
