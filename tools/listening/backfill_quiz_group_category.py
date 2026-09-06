# -*- coding: utf-8 -*-
"""
用法：
  python backfill_quiz_group_category.py docs/private/<slug>/data.js [--write]

一次性迁移脚本：`jp-textbook-lesson` skill 的单词测试 tab 分类从"这个词的例句
来源是会话/课文/人工补写"（category = "dialogue"/"text"/"other"，由
build_vocab_quiz_data.py 早期版本写入）改成"这个词自己在生词表里属于哪个
小节"（category = 该词在"生词"tab 下所属 question 分组的文字，比如
"生词表1"/"生词表2·语法与表达"）之后，已经发布的旧 data.js 里 `quiz[]` 的
`category` 字段还是旧的三分类值，需要重新映射成新的小节名。

不需要原始的 vocab_words.json/occurrences.json（这些工作文件按约定不提交、
有些课已经清理掉）——data.js 里"生词"tab 自己的 `tabs[].questions[].
sentences[].id` 就是每个词的真实编号、`question` 就是它所属小节的文字，
直接从已发布的页面反查回来即可，跟 verify_quiz_ids.py 反查"生词卡片真实
音频编号"是同一个思路。

**quiz 词条的 id 在「生词」tab 里找不到对应句子时**（真实案例 textbook-sjp-
zg-l17：早期"一词多例句"实现是"同一个词复制多张卡片"，后来改成"一张卡片
挂 moreExamples 数组"时，重复卡片和它们各自独占的音频文件都被合并/删除
掉了，但 quiz[] 里对应这些重复卡片的 14 条词条没有跟着更新，`id` 还指向
已经不存在的音频编号——`build_vocab_quiz_data.py`/`verify_quiz_ids.py`
都是按"一张卡片对一条 quiz 词条"的假设写的，没预料到"一词多例句"合并后
"多条 quiz 词条对一张卡片"这种情况），退而按 `text` 字段反查「生词」tab
里是否有唯一一张读音/含义都相同的卡片：**只有唯一匹配时才自动纠正**（把
这条词条的 `id` 也一并改成那张卡片的真实 id，顺带修好了"听音频写假名"
题播放不存在音频的问题），`text` 相同的卡片有 0 张或不止 1 张（比如同一课
里读音不同的同形词、真的是词表本身缺了这个词）一律直接报错交给人工核查，
不去猜——这类"当前用来消歧的唯一线索用完了"的情况，跟 SKILL.md"常见坑"
里记录的其它几处"宁可报错也不猜测"的先例是同一个原则。

默认只打印一份"旧 id/分类 → 新 id/分类"迁移报告，不改文件；加 `--write`
才真的写回 data.js。只改 `quiz[].id`/`quiz[].category`，不碰其它任何字段。
"""
import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_page import normalize_numbers  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_js_path")
    ap.add_argument("--write", action="store_true", help="真的写回文件，不传就只打印预览")
    ap.add_argument("--vocab-label", default="生词", help="生词 tab 的标签文字，默认“生词”")
    args = ap.parse_args()

    raw = open(args.data_js_path, encoding="utf-8").read()
    body = raw[raw.index("{"): raw.rindex("}") + 1]
    lesson_data = json.loads(body)

    quiz = lesson_data.get("quiz")
    if quiz is None:
        print('FAIL: data.js 里没有 "quiz" 字段，这个页面没有单词测试 tab')
        sys.exit(1)

    id_to_group = {}
    text_to_ids = {}
    for tab in lesson_data.get("tabs", []):
        if tab.get("mondai") != args.vocab_label:
            continue
        for q in tab["questions"]:
            for s in q["sentences"]:
                id_to_group[s["id"]] = q["question"]
                text = "".join(t["text"] for t in s.get("tokens", []))
                text_to_ids.setdefault(text, []).append(s["id"])
    if not id_to_group:
        print(f"FAIL: 没找到标签为「{args.vocab_label}」的 tab，检查 --vocab-label 是否正确")
        sys.exit(1)

    orphans = [entry for entry in quiz if entry["id"] not in id_to_group]
    unresolvable = [e for e in orphans if len(text_to_ids.get(e["text"], [])) != 1]
    if unresolvable:
        for e in unresolvable:
            cands = text_to_ids.get(e["text"], [])
            print(f"FAIL: quiz 词条 id={e['id']} text={e['text']!r} 在「{args.vocab_label}」"
                  f"tab 里找不到对应句子，按 text 反查也没有唯一匹配（候选 id: {cands}），"
                  f"需要人工核查（应该先跑 verify_quiz_ids.py 排除更常见的整体偏移问题）")
        sys.exit(1)

    id_fixes = 0
    counts = {}
    for entry in quiz:
        old_id = entry["id"]
        if old_id not in id_to_group:
            new_id = text_to_ids[entry["text"]][0]
            entry["id"] = new_id
            id_fixes += 1
        new = id_to_group[entry["id"]]
        old = entry.get("category")
        counts.setdefault((old, new), 0)
        counts[(old, new)] += 1
        entry["category"] = new

    print(f"{args.data_js_path}: {len(quiz)} 条词条，迁移明细（旧分类→新分类: 数量）：")
    for (old, new), n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {old!r} -> {new!r}: {n}")
    if id_fixes:
        print(f"另外按 text 反查修正了 {id_fixes} 条词条的 id（原 id 在「{args.vocab_label}」"
              f"tab 里已经不存在，多半是引用了被合并/删除的重复卡片）")

    if not args.write:
        print("(预览模式，没有写回文件；确认分类看起来合理后加 --write 真正写入)")
        return

    with open(args.data_js_path, "w", encoding="utf-8") as f:
        f.write("window.LESSON_DATA = ")
        json.dump(normalize_numbers(lesson_data), f, ensure_ascii=False, indent=2)
        f.write(";\n")
    print(f"wrote back to {args.data_js_path}")


if __name__ == "__main__":
    main()
