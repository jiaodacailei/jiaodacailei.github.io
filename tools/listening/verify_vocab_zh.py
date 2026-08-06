# -*- coding: utf-8 -*-
"""
用法：
  python verify_vocab_zh.py docs/private/<slug>/index.html

生词表条目的 `zh` 字段（中文释义）有时会在抄写截图时把词条自己的原文
（含语法笔记占位符"〜"）误当成释义的一部分抄进去——真实案例
（textbook-sjp-zg-l12）：截图里"〜問目　第〜题，第〜个问题"这样"词条+
释义"两栏并排的格式，抄的时候把整行（含左边的词条本身）都塞进了 `zh`
字段，变成"〜問目 第〜题，第〜个问题"，真正的释义前面多出一段词条原文
的重复；"〜以内 〜以内"则是把词条整个复制了一遍冒充释义，`zh` 字段里
完全没有真正的中文内容。这个脚本批量检查这种模式，用户在页面编辑模式
里手动修正之后跑一遍，确认没有其它已发布课程漏网。

**不要跟"zh 完全等于词条本身"这种情况搞混**——比如"〜量"这条词条的
`zh` 字段就是"〜量"，跟词条完全相同，这是正常情况（教材原文对这类
语法后缀本来就没有额外的中文释义，只是重复标注一遍这个后缀本身），
**不算 bug**，脚本不会报告这种情况。真正要抓的是"zh 以词条原文开头、
后面还紧跟着一段明显不同的内容"这种模式——这说明本该只保留后半段
真正的释义，词条原文那部分是抄录时混进来的多余内容。

只报告，不改文件——`zh` 该保留成什么样应该由人判断（后半段那部分才是
真正的释义，词条原文那部分应该整个删掉，不是简单去掉重复字符）。
"""
import sys
import os
import json
import argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def check_data_driven(data_js_path):
    raw = open(data_js_path, encoding="utf-8").read()
    raw = raw[raw.index("{"):raw.rindex("}") + 1]
    data = json.loads(raw)

    total = 0
    flagged = []
    for tab in data.get("tabs", []):
        for q in tab.get("questions", []):
            for s in q.get("sentences", []):
                total += 1
                text = "".join(t["text"] for t in s.get("tokens", []))
                zh = s.get("zh") or ""
                if not text or not zh or zh == text:
                    continue
                if zh.startswith(text) and zh[len(text):len(text) + 1] in (" ", "　"):
                    flagged.append((s.get("id"), text, zh))
    return total, flagged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html_path")
    args = ap.parse_args()

    data_js_path = os.path.join(os.path.dirname(args.html_path), "data.js")
    if not os.path.exists(data_js_path):
        print(f"没找到 {data_js_path}——这个脚本只支持 --data-driven 生成的页面")
        sys.exit(1)

    total, flagged = check_data_driven(data_js_path)
    print(f"{args.html_path}: 共检查 {total} 句")
    if not flagged:
        print("OK: 没有发现 zh 字段开头混入词条原文的情况")
        return
    print(f"\n{len(flagged)} 条 zh 字段疑似混入了词条原文，检查是不是抄写时多带了一段：")
    for sid, text, zh in flagged:
        print(f"  id={sid}: 词条「{text}」，zh 现在是「{zh}」——大概率应该去掉开头的「{text}」")
    sys.exit(1)


if __name__ == "__main__":
    main()
