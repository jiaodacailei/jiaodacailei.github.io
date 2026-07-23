# -*- coding: utf-8 -*-
"""
用法：
  python build_vocab_quiz_data.py <vocab_words.json> <sentences.json> \
      <occurrences.json> <authored_examples.json> <out_quiz_data.json>

"单词测试" tab 专用（`jp-textbook-lesson` skill 用到）：把生词表 + 每个生词的
例句来源（真实出现在会话/课文里的句子，或人工补写的例句）合并成
`build_page.py --quiz-json` 直接能吃的数据，前端用这份数据现算"填空题/
音频写假名/中文写假名/日文写中文"四种题目，不在这里预先展开成 400 条——
题目怎么问是纯前端逻辑，这里只负责把每个词该有的素材备齐。

<vocab_words.json>：跟 build_vocab_from_wordlist.py 用的是同一份格式，但这里
  只用 id/text/zh/kana 四个字段（audio 路径不需要传，跟 build_page.py 生成
  生词卡片时用的是同一条规则：`audio/seg-{id:03d}.mp3`，由 build_page.py 自己
  拼，不在这份数据里重复）。id 允许带不带 "a" 前缀都行，这里统一转成不带前缀
  的数字字符串再往下用。

<sentences.json>：{"dialogue": [{"ja":..., "zh":...}, ...], "text": [...]}
  —— 从已生成页面的会话/课文 tab 抽出来的句子，供 occurrences.json 按
  (src, idx) 定位到具体是哪一句。

<occurrences.json>：{"<word_id>": {"src": "dialogue"|"text", "idx": N,
  "blank": "这句里实际要挖空的原文片段（可以是词的活用形，不强求跟词典形一致，
  比如动词读成て形/た形就直接填那个活用形）"} , ...}
  —— 人工核实过的"这个词真的出现在这句里"的记录，不是靠脚本模糊匹配自动生成
  （汉字词干/假名活用的自动匹配极易出现假阳性，比如"入れる"的汉字"入"会
  误匹配到"入浴"，"申し上げる"里的"お/ご"两个假名单字几乎能匹配上所有句子——
  这类误匹配详见 SKILL.md"常见坑"，人工过一遍全部候选句是唯一可靠做法）。

<authored_examples.json>：{"<word_id>": {"ja": "补写的例句", "zh": "对应中译",
  "blank": "例句里对应这个词的原文片段"}, ...}
  —— 会话/课文里确实没有出现的词，人工现造一个自然例句（教材程度、跟原文
  风格一致），填空题一样能覆盖到。

两份来源合起来必须覆盖 <vocab_words.json> 里的每一个词、且不重复覆盖同一个
词——脚本会硬报错提醒，不悄悄跳过缺失或忽略重复。
"""
import sys
import json
import argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def norm_id(raw_id):
    s = str(raw_id)
    return s[1:] if s.startswith("a") else s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vocab_words_json")
    ap.add_argument("sentences_json")
    ap.add_argument("occurrences_json")
    ap.add_argument("authored_examples_json")
    ap.add_argument("out_json")
    args = ap.parse_args()

    words = json.load(open(args.vocab_words_json, encoding="utf-8"))
    sentences = json.load(open(args.sentences_json, encoding="utf-8"))
    occurrences = json.load(open(args.occurrences_json, encoding="utf-8"))
    authored = json.load(open(args.authored_examples_json, encoding="utf-8"))

    word_ids = [norm_id(w["id"]) for w in words]
    occ_ids = set(norm_id(k) for k in occurrences)
    auth_ids = set(norm_id(k) for k in authored)
    dup = occ_ids & auth_ids
    if dup:
        print(f"FAIL: {len(dup)} 个词同时出现在 occurrences.json 和 authored_examples.json 里，"
              f"每个词只能有一个例句来源: {sorted(dup)}")
        sys.exit(1)
    missing = set(word_ids) - occ_ids - auth_ids
    if missing:
        print(f"FAIL: {len(missing)} 个词在 occurrences.json / authored_examples.json 里都没有对应例句: "
              f"{sorted(missing)}")
        sys.exit(1)
    extra = (occ_ids | auth_ids) - set(word_ids)
    if extra:
        print(f"FAIL: occurrences.json/authored_examples.json 里有 {len(extra)} 个 id "
              f"在 vocab_words.json 里找不到对应词，检查是不是 id 打错了: {sorted(extra)}")
        sys.exit(1)

    quiz = []
    for w in words:
        wid = norm_id(w["id"])
        entry = {
            "id": int(wid),
            "text": w["text"],
            "kana": w.get("kana", w["text"]),
            "zh": w["zh"],
        }
        occ_key = next((k for k in occurrences if norm_id(k) == wid), None)
        if occ_key is not None:
            o = occurrences[occ_key]
            sent = sentences[o["src"]][o["idx"]]
            if o["blank"] not in sent["ja"]:
                print(f"FAIL: word {wid} 的 occurrence blank {o['blank']!r} "
                      f"不是句子 {sent['ja']!r} 的子串，检查数据是否过期")
                sys.exit(1)
            entry["sentence"] = sent["ja"]
            entry["sentence_zh"] = sent["zh"]
            entry["blank"] = o["blank"]
        else:
            auth_key = next(k for k in authored if norm_id(k) == wid)
            a = authored[auth_key]
            if a["blank"] not in a["ja"]:
                print(f"FAIL: word {wid} 的 authored blank {a['blank']!r} 不是例句 {a['ja']!r} 的子串")
                sys.exit(1)
            entry["sentence"] = a["ja"]
            entry["sentence_zh"] = a["zh"]
            entry["blank"] = a["blank"]
        quiz.append(entry)

    json.dump(quiz, open(args.out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"wrote {len(quiz)} quiz entries to {args.out_json}")


if __name__ == "__main__":
    main()
