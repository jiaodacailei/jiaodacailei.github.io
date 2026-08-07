# -*- coding: utf-8 -*-
"""
用法：
  python backfill_quiz_sentence.py docs/private/<slug>/index.html [--write]

一次性迁移脚本：给"生词填空模式借用单词测试例句"这个功能上线之前就已经
生成好 data.js 的课（l10/l11/l12——l13 是这个功能实现时正在跑的那一课，
data.js 已经是带 quizSentence 字段的最新版，不需要这个脚本）补上生词卡片的
`blanks`/`quizSentence` 两个字段。逻辑跟 build_page.py 里 sentence_to_data()
完全一致，但不需要重新走一遍完整生成流程（那些课的 tools/listening/work/
工作目录早已按约定清理掉，没有 enriched_combined.json/quiz_data.json 可用）
——因为同一份信息已经在 data.js 自己的顶层 `quiz` 数组里（单词测试用的
sentence/blank 字段，跟对应生词卡片是同一个 `id`），直接从 data.js 自己读
出来反哺回去就够了。

只改每个符合条件的 sentence 对象的这两个字段，不碰其它任何内容（包括不
碰音频），key 顺序、pretty-print 格式（indent=2）都跟 build_page.py 生成时
一致，可以放心用 git diff 确认改动范围只有这些。已经有 `blanks`（会话/课文
里人工写的语法点填空）的句子原样跳过，不会被覆盖。

默认只打印一份"会给哪些 id 补上"的预览，不改文件；加 --write 才真的写回。
"""
import sys
import os
import json
import argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html_path")
    ap.add_argument("--write", action="store_true", help="真的写回文件，不传就只打印预览")
    args = ap.parse_args()

    data_js_path = os.path.join(os.path.dirname(args.html_path), "data.js")
    if not os.path.exists(data_js_path):
        print(f"FAIL: 没找到 {data_js_path}，这不是 --data-driven 生成的页面")
        sys.exit(1)

    raw = open(data_js_path, encoding="utf-8").read()
    start, end = raw.index("{"), raw.rindex("}") + 1
    prefix, body, suffix = raw[:start], raw[start:end], raw[end:]
    data = json.loads(body)

    quiz = data.get("quiz")
    if not quiz:
        print("FAIL: data.js 里没有 quiz 字段，这个页面没有単語テスト tab")
        sys.exit(1)
    quiz_by_id = {q["id"]: q for q in quiz}

    patched = []
    for tab in data.get("tabs", []):
        for q in tab.get("questions", []):
            for s in q.get("sentences", []):
                if s.get("blanks"):
                    continue
                entry = quiz_by_id.get(s["id"])
                if entry and entry.get("sentence") and entry.get("blank"):
                    s["blanks"] = [entry["blank"]]
                    s["quizSentence"] = entry["sentence"]
                    patched.append(s["id"])

    if not patched:
        print(f"{args.html_path}: 没有需要补的条目（已经补过，或者本来就没有生词 tab）")
        return
    print(f"{args.html_path}: 会给 {len(patched)} 个生词卡片补上 quizSentence"
          f"（id={patched[:3]}...{patched[-3:]}）")

    if not args.write:
        print("(预览模式，没有写回文件；确认数量看起来合理后加 --write 真正写入)")
        return

    with open(data_js_path, "w", encoding="utf-8") as f:
        f.write(prefix)
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write(suffix)
    print(f"wrote back to {data_js_path}")


if __name__ == "__main__":
    main()
