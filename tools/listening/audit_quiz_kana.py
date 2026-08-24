# -*- coding: utf-8 -*-
"""
用法：
  python audit_quiz_kana.py                    # 扫全站 docs/private/*/data.js
  python audit_quiz_kana.py docs/private/textbook-sjp-zg-l15/data.js [...]

`jp-textbook-lesson` skill 用：扫已发布的 `data.js` 里 `quiz`（单词测试 tab）
数组，抓两类"标准答案本身就是错的"数据坏值——这两类都在真实课程里发生过、
而且都是"生成阶段的校验只挡得住新生成的，挡不住已经发布的旧页面"：

1. **`kana` 字段里混进了词典抄录习惯保留的占位符"〜"/"～"**（真实案例
   textbook-sjp-zg-l15"〜人前"，标准答案变成"～にんまえ"，用户照实际发音
   写"にんまえ"被判错——这个符号根本不发音）。`build_vocab_quiz_data.py` 的
   `kana_for()` 已经在生成阶段修了（两条分支都会 `.replace()` 掉两种
   Unicode 码位），但**已经发布的 `data.js` 不会因为改了生成函数就自动
   更新**——这个脚本补上"扫已发布内容"这一步，不用每次改完生成逻辑都手工
   `grep` 一遍全站。
2. **`kana` 字段跟 `text` 一字不差、但 `text` 含汉字**（真实案例 textbook-
   sjp-zg-l14"〜次"/"〜未満"，`kana` 被误填成跟 `text` 完全相同的值，不是
   真的读音）。`build_vocab_quiz_data.py`/`build_page.py` 生成阶段现在都会
   直接 `raise ValueError` 拦下来，但同样只挡得住新生成——已发布的旧页面
   如果是更早期版本生成的，仍然可能带着这个坏值。

跟 `audit_furigana.py` 不是同一类工具，不要混用：`audit_furigana.py` 扫的是
`enriched.json`（生成前的工作文件）+ 现场重跑 `tokenize_ja()`/`_split_kana_
segments()` 去核对会话/课文/生词卡片本身的读音标注对不对；这个脚本扫的是
已经生成好的 `data.js` 里 `quiz[]` 数组（单词测试题库），纯字符串模式匹配，
不需要 pykakasi，因为要抓的是"数据本身形状不对"，不是"读音猜错了"。

只报告，不自动修——找到的坏值直接在 `data.js` 里手工改 `kana` 字段（去掉
占位符，或者补上真实读音），改完不用重新跑 `build_page.py`（`quiz` 数组
是纯数据，前端直接读，不涉及音频切割/跟读时间戳）。
"""
import sys
import os
import re
import json
import argparse
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_page import _is_kanji  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PLACEHOLDER_CHARS = ("〜", "～")  # U+301C WAVE DASH / U+FF5E FULLWIDTH TILDE


def load_quiz(data_js_path):
    content = open(data_js_path, encoding="utf-8").read()
    m = re.match(r"^\s*window\.LESSON_DATA\s*=\s*(.*);\s*$", content, re.S)
    if not m:
        return None
    data = json.loads(m.group(1))
    return data.get("quiz")


def audit_one(data_js_path):
    quiz = load_quiz(data_js_path)
    if quiz is None:
        return []
    findings = []
    for entry in quiz:
        text = entry.get("text", "")
        kana = entry.get("kana")
        if not kana:
            continue
        if any(ch in kana for ch in PLACEHOLDER_CHARS):
            findings.append((entry.get("id"), text, kana, "占位符〜/～混进了标准答案"))
        elif kana == text and any(_is_kanji(ch) for ch in text):
            findings.append((entry.get("id"), text, kana, "kana跟text一字不差、但text含汉字"))
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_js_paths", nargs="*", help="不传就扫全站 docs/private/*/data.js")
    args = ap.parse_args()

    paths = args.data_js_paths
    if not paths:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        paths = sorted(glob.glob(os.path.join(repo_root, "docs", "private", "*", "data.js")))

    total_findings = 0
    for path in paths:
        findings = audit_one(path)
        if findings:
            print(f"{path}:")
            for id_, text, kana, reason in findings:
                print(f"  id={id_} text={text!r} kana={kana!r} -- {reason}")
            total_findings += len(findings)
    if total_findings == 0:
        print(f"共检查 {len(paths)} 个 data.js，quiz 数组没有发现已知的坏值模式")
    else:
        print(f"共检查 {len(paths)} 个 data.js，发现 {total_findings} 处")


if __name__ == "__main__":
    main()
