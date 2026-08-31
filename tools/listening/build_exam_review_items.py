# -*- coding: utf-8 -*-
"""
用法：
  python build_exam_review_items.py <exam data.js路径>

N2真题模考页（n2-exam-*）用：从問題1〜9（漢字読み/表記/語形成/文脈規定/
言い換え類義/用法/文法1/文法2/文法3）里按题抽出目标词/语法点，写进
data.js顶层的`reviewItems`字段，供页面「重点词汇语法」tab渲染——不是
答题流程的一部分，纯参考列表。

読解部分（問題10〜14）不抽：那部分是整篇文章，没有"这题考的是哪个词"
这种明确标注，抽取要靠主观判断挑生词，没有官方解析背书，跟前9题的
可靠度不是一个量级，故意不做。见 n2-exam/2020-12/LOG.md「重点词汇
语法」这一节的讨论。

按大题类型分三种抽取方式（源自 build_exam_data.py 生成的 question 对象
本身就有的字段，不解析中文解析文本去猜哪段是哪个词的释义——explanationZh
整段原文本来就是准确的解析，直接当notes原样展示，没有必要也没必要冒险去
正则切):
  - 問題1/2/3/4/5/7/8（都有 q.stem，交卷后显示的"填好正确答案"完整句，
    自带音频+逐字furigana）：type="sentence"，直接用 q.stem。
  - 問題6（用法——题干只给一个裸词 q.stemWord，没有 q.stem；正确的例句
    藏在 q.options[q.answer-1].sentences[0] 里）：type="word"，
    headTokens/headAudio 来自 stemWord，stemTokens/stemAudio 来自
    对应正确选项的例句。
  - 問題9（段落挖空——4道题共享同一篇文章，每道题各自的 q.stem 是
    null，完整段落连音频都在 block.passageSentences 这个数组里，
    每句各自一个mp3）：4题合并成1条 type="passage" 记录，音频/正文
    复用 block.passageSentences，4道题的解析各自列进 notes 数组。
"""
import sys
import json
import re


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    raw = open(path, encoding="utf-8").read()
    prefix = raw[: raw.index("{")]
    body = raw[raw.index("{") :]
    body = re.sub(r";\s*$", "", body.strip())
    d = json.loads(body)

    review_items = []
    for m in d["mondaiList"]:
        if m["mondai"] > 9:
            continue
        if m["mondai"] == 9:
            for b in m["blocks"]:
                notes = [
                    {"qLabel": str(q["id"]) + "番", "zh": q["explanationZh"]}
                    for q in b["questions"]
                ]
                review_items.append(
                    {
                        "type": "passage",
                        "mondai": m["mondai"],
                        "mondaiLabel": m["label"],
                        "qLabel": str(b["questions"][0]["id"]) + "〜" + str(b["questions"][-1]["id"]) + "番",
                        "passageSentences": b["passageSentences"],
                        "notes": notes,
                    }
                )
            continue
        for b in m["blocks"]:
            for q in b["questions"]:
                if m["mondai"] == 6:
                    opt = q["options"][q["answer"] - 1]
                    sent = opt["sentences"][0]
                    review_items.append(
                        {
                            "type": "word",
                            "mondai": m["mondai"],
                            "mondaiLabel": m["label"],
                            "qLabel": str(q["id"]) + "番",
                            "headTokens": q["stemWord"]["tokens"],
                            "headAudio": q["stemWord"]["audio"],
                            "stemTokens": sent["tokens"],
                            "stemAudio": sent["audio"],
                            "zh": q["explanationZh"],
                        }
                    )
                else:
                    review_items.append(
                        {
                            "type": "sentence",
                            "mondai": m["mondai"],
                            "mondaiLabel": m["label"],
                            "qLabel": str(q["id"]) + "番",
                            "stemTokens": q["stem"]["tokens"],
                            "stemAudio": q["stem"]["audio"],
                            "zh": q["explanationZh"],
                        }
                    )

    d["reviewItems"] = review_items
    by_type = {}
    for it in review_items:
        by_type[it["type"]] = by_type.get(it["type"], 0) + 1
    print("extracted", len(review_items), "review items:", by_type)

    out = prefix + json.dumps(d, ensure_ascii=False, indent=2) + ";\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print("written back to", path)


if __name__ == "__main__":
    main()
