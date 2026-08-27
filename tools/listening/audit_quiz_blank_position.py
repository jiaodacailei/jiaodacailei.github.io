# -*- coding: utf-8 -*-
"""
用法：
  python audit_quiz_blank_position.py                    # 扫全站 docs/private/*/data.js
  python audit_quiz_blank_position.py docs/private/textbook-sjp-zg-l15/data.js [...]

`jp-textbook-lesson` skill 用：扫已发布的 `data.js` 里"填空题的空挖错位置"这一类
坑——真实案例 textbook-sjp-zg-l15 单词"都"（みやこ，首都），例句"京都は昔の都
だった。"，前端挖空逻辑固定用 `sentence.indexOf(blank)` 找第一个匹配位置，但
"都"这个字同时也是"京都"这个专有名词的最后一个字，第一个匹配落在"京都"内部
（挖出来变成"京____は昔の都だった。"），真正该挖的是后面"昔の都"里独立成词的
那个"都"，indexOf 天生只会找第一个匹配，不知道哪个才是"正确的那个"。

判定思路：不去猜"哪个匹配才是对的"（那需要真正的分词，这个脚本不做），只找
"明显更可疑"的信号——第一个匹配的位置，如果紧挨着的前一个字符是汉字（且 blank
自己开头也是汉字），说明这个匹配跟前一个字融合成了更长的连续汉字串，是"整词
的一部分"而不是独立成词的匹配；如果后面还有一个"干净"的匹配（前后都不是紧挨着
汉字，即真正独立成词的位置），那前端 indexOf 挖到的很可能是错的那个。这个信号
只对"参与判断的都是汉字"的场景有效，假名/片假名词天生不会有这类"融进更长汉字
串"的问题，不在这个脚本的报告范围内。

扫两类字段（都用同一个判定函数）：
1. `quiz[]` 数组：`sentence` + `blank`（单词测试"填空题"用）。
2. 会话/课文/生词卡片的 `quizSentence` + `blanks[]`（生词卡片自带的填空练习
   模式，`docs/js/listening-page.js` 里 `searchFrom` 累进查找，第一个 blank
   同样是从位置0开始用 indexOf 找，同一个坑）。

只报告，不自动改——挖空位置错了通常意味着例句本身选得不好（比如拿一个包含
目标字的专有名词当例句），比"调整算法"更彻底的做法是换一句不产生歧义的例句，
这需要人工判断换成哪句更自然，脚本判断不了。
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


def find_all(haystack, needle):
    positions = []
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + 1
    return positions


def is_embedded(sentence, idx, blank):
    """这个匹配的开头/结尾是不是跟紧挨着的字符融合成了更长的连续汉字串。"""
    if blank and _is_kanji(blank[0]) and idx > 0 and _is_kanji(sentence[idx - 1]):
        return True
    end = idx + len(blank)
    if blank and _is_kanji(blank[-1]) and end < len(sentence) and _is_kanji(sentence[end]):
        return True
    return False


def check_pair(sentence, blank):
    if not sentence or not blank or blank not in sentence:
        return None
    positions = find_all(sentence, blank)
    if len(positions) < 2:
        return None
    first_embedded = is_embedded(sentence, positions[0], blank)
    if not first_embedded:
        return None
    has_clean_later = any(not is_embedded(sentence, p, blank) for p in positions[1:])
    if has_clean_later:
        return positions[0]
    return None


def load_data(data_js_path):
    content = open(data_js_path, encoding="utf-8").read()
    m = re.match(r"^\s*window\.LESSON_DATA\s*=\s*(.*);\s*$", content, re.S)
    if not m:
        return None
    return json.loads(m.group(1))


def audit_one(data_js_path):
    data = load_data(data_js_path)
    if data is None:
        return []
    findings = []
    for entry in (data.get("quiz") or []):
        bad_idx = check_pair(entry.get("sentence"), entry.get("blank"))
        if bad_idx is not None:
            findings.append((entry.get("id"), entry.get("blank"), entry.get("sentence"), "quiz.sentence/blank"))
    for tab in (data.get("tabs") or []):
        for mondai in (tab.get("questions") or []):
            for card in (mondai.get("sentences") or []):
                qs = card.get("quizSentence")
                for b in (card.get("blanks") or []):
                    bad_idx = check_pair(qs, b)
                    if bad_idx is not None:
                        findings.append((card.get("id"), b, qs, "card.quizSentence/blanks"))
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_js_paths", nargs="*", help="不传就扫全站 docs/private/*/data.js")
    args = ap.parse_args()

    paths = args.data_js_paths
    if not paths:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        paths = sorted(glob.glob(os.path.join(repo_root, "docs", "private", "*", "data.js")))

    total = 0
    for path in paths:
        findings = audit_one(path)
        if findings:
            print(f"{path}:")
            for id_, blank, sentence, where in findings:
                print(f"  id={id_} blank={blank!r} sentence={sentence!r} -- {where} 第一个匹配疑似挖错位置")
            total += len(findings)
    if total == 0:
        print(f"共检查 {len(paths)} 个 data.js，没有发现挖空位置可疑的情况")
    else:
        print(f"共检查 {len(paths)} 个 data.js，发现 {total} 处")


if __name__ == "__main__":
    main()
