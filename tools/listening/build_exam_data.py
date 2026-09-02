# -*- coding: utf-8 -*-
"""
用法：
  python build_exam_data.py <四份合并的raw json所在目录> <输出data.js路径>

例：
  python build_exam_data.py tools/listening/work/n2exam-202412 docs/private/n2-exam/2024-12/data.js

从4个transcribe agent产出的raw json（mondai1-5.json/mondai6-9.json/
mondai10-11.json/mondai12-14.json，字段约定见各自transcribe任务的prompt）
组装成exam-page.js能直接吃的`window.EXAM_DATA`（mondaiList结构）。

**这一版不生成音频**——所有audio/duration字段都是null占位。先把文本/结构
这部分跑通、在浏览器里过一遍视觉+交互没问题，再单独跑一个音频合成脚本
把null填成真实音频路径（复用2020-12案例验证过的edge-tts+faster-whisper
对齐方案，那部分工作量大、耗时长，不值得在文本还没定稿前先做）。

## 各大题的stemHtml渲染字段约定（跟docs/js/exam-page.js的stemHtml()对应）

- 問題1/2/3/4/5/7（单句挖空型）：`stemBlank`（挖空原文，blank token不注音，
  防剧透）+ `stem`（正确答案填入后的完整句，只存数据不渲染，给
  build_exam_vocab.py读audio用）。
- 問題6（用法）：`stemWord`（裸词，不挖空，出示哪个词本身不算剧透）。
- 問題8（★排序）：`stemBlank`（框架句，4个占位符+★原样保留）+ `stem`
  （从解析文本里的"正确语序：..."正则抽出来的、已经按真实顺序拼好的完整
  句——不需要人工维护override表，2024-12这套解析文本本身就带着数字前缀
  标好了每个片段的位置，比2020-12当时人工核对省事很多）。
- 問題9〜14（純读解，没有挖空剧透问题）：`stemInstruction`（题目问句本身，
  問題9是"文章中の48に入れるのに..."这种自动生成的模板文案）。

## 段落(passage)约定
- 問題1〜8：每题一个block，`passageSentences`留空数组（没有独立段落）。
- 問題9：整个大题只有一个block，`is_mondai9: true`，`passageSentencesBlank`
  （挖空版，48/49/50/51占位符保留成blank token）+ `passageSentences`
  （正确答案填好的版本，只存数据，exam-page.js设计上不渲染这份，
  build_exam_vocab.py会用它按句查目标词的例句）。
- 問題10：5个block，各自一段短文+1题。
- 問題11：4个block（这套2024-12真题確認是(1)〜(4)四篇，不是老案例的3篇），
  各自一段长文+2题。
- 問題12（AB比較）：1个block，passageSentences把A/B两段拼成一串（各自前面
  插一句纯"A"/"B"标签句方便阅读区分），2题。
- 問題13：1个block，1段长文+3题。
- 問題14（情報検索）：1个block，`documentText`按行拆成句子（本来就是价目表
  这类结构化内容，没有天然的"句子"概念，直接按换行拆), 2题，答案来自正答表
  （没有explanationZh，问题里也没有这个字段）。
"""
import sys
import os
import re
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_page import tokenize_ja  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BLANK_RE = re.compile(r"<<(.*?)>>", re.S)
MONDAI8_ORDER_RE = re.compile(r"正确语序[：:](.+?)句意[：:]", re.S)
FRAGMENT_NUM_RE = re.compile(r"[1-4]\.")

INSTRUCTION = {
    1: "＿＿＿の言葉の読み方として最もよいものを、1・2・3・4から一つ選びなさい。",
    2: "＿＿＿の言葉を漢字で書くとき、最もよいものを、1・2・3・4から一つ選びなさい。",
    3: "（　）に入れるのに最もよいものを、1・2・3・4から一つ選びなさい。",
    4: "（　）に入れるのに最もよいものを、1・2・3・4から一つ選びなさい。",
    5: "＿＿＿の言葉に意味が最も近いものを、1・2・3・4から一つ選びなさい。",
    6: "次の言葉の使い方として最もよいものを、1・2・3・4から一つ選びなさい。",
    7: "次の文の（　）に入れるのに最もよいものを、1・2・3・4から一つ選びなさい。",
    8: "次の文の★に入る最もよいものを、1・2・3・4から一つ選びなさい。",
    9: "次の文章を読んで、文章全体の内容を考えて、48から51の中に入る最もよいものを、1・2・3・4から一つ選びなさい。",
    10: "次の(1)から(5)の文章を読んで、後の問いに対する答えとして最もよいものを、1・2・3・4から一つ選びなさい。",
    11: "次の(1)から(4)の文章を読んで、後の問いに対する答えとして最もよいものを、1・2・3・4から一つ選びなさい。",
    12: "次のAとBの文章を読んで、後の問いに対する答えとして最もよいものを、1・2・3・4から一つ選びなさい。",
    13: "次の文章を読んで、後の問いに対する答えとして最もよいものを、1・2・3・4から一つ選びなさい。",
    14: None,  # 問題14用逐题transcribe到的instructionText，不用这份写死的
}
MONDAI_LABEL_SUFFIX = {
    1: "漢字読み", 2: "表記", 3: "語形成", 4: "文脈規定", 5: "言い換え類義",
    6: "用法", 7: "文法1", 8: "文法2", 9: "文法3",
    10: "内容理解（短文）", 11: "内容理解（中文）", 12: "統合理解",
    13: "主張理解（長文）", 14: "情報検索",
}


def tok(text):
    return tokenize_ja(text) if text else []


def split_blank(stem_text):
    m = BLANK_RE.search(stem_text)
    if not m:
        raise ValueError("no <<...>> blank marker found in: " + stem_text[:50])
    return stem_text[: m.start()], m.group(1), stem_text[m.end() :]


def stem_blank_field(stem_text):
    pre, blank, post = split_blank(stem_text)
    toks = tok(pre) + [{"text": blank, "blank": True}] + tok(post)
    return {"tokens": toks}


def stem_filled_field(stem_text, answer_text):
    pre, _blank, post = split_blank(stem_text)
    toks = tok(pre) + tok(answer_text) + tok(post)
    return {"tokens": toks, "audio": None, "duration": None}


def option_field(idx, text):
    return {"idx": idx, "tokens": tok(text), "audio": None}


# 「」『』（）() 内部出现的。/！/？不当句子分界，避免把带引号的对话/例句切碎。
_OPEN = set("「『（(")
_CLOSE = set("」』）)")
_ENDERS = set("。！？")


def split_sentences(text):
    text = text.strip()
    if not text:
        return []
    sents = []
    buf = ""
    depth = 0
    for ch in text:
        buf += ch
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth = max(0, depth - 1)
        elif ch in _ENDERS and depth == 0:
            sents.append(buf)
            buf = ""
    if buf.strip():
        sents.append(buf)
    return [s.strip() for s in sents if s.strip()]


def passage_sentences_plain(text):
    return [{"tokens": tok(s), "audio": None, "duration": None} for s in split_sentences(text)]


def passage_sentences_with_blanks(text):
    """给問題9挖空版用——按句拆开，每句内部可能含<<48>>这种占位符，转成
    blank token（不注音，跟stem_blank_field同一个道理，不过這裡是数字占位符
    本身没有可读内容，主要是保留视觉上的挖空样式，不是防剧透）。"""
    result = []
    for s in split_sentences(text):
        toks = []
        last = 0
        for m in BLANK_RE.finditer(s):
            toks.extend(tok(s[last : m.start()]))
            toks.append({"text": m.group(1), "blank": True})
            last = m.end()
        toks.extend(tok(s[last:]))
        result.append({"tokens": toks, "audio": None, "duration": None})
    return result


def fill_blanks(text, answer_by_num):
    def _sub(m):
        return answer_by_num[m.group(1)]

    return BLANK_RE.sub(_sub, text)


def mondai8_correct_sentence(explanation_zh):
    m = MONDAI8_ORDER_RE.search(explanation_zh)
    if not m:
        return None
    raw = m.group(1).strip()
    return FRAGMENT_NUM_RE.sub("", raw)


def block_simple(q):
    """問題1/2/3/4/5/7 共用：一题一个block，stemBlank+stem，plain options。"""
    answer_text = q["options"][q["answer"] - 1]
    return {
        "passageSentences": [],
        "questions": [
            {
                "id": q["id"],
                "answer": q["answer"],
                "stemBlank": stem_blank_field(q["stemText"]),
                "stem": stem_filled_field(q["stemText"], answer_text),
                "options": [option_field(i + 1, o) for i, o in enumerate(q["options"])],
                "explanationZh": q["explanationZh"],
            }
        ],
    }


def block_mondai6(q):
    options = []
    for i, opt_text in enumerate(q["options"]):
        sents = [{"tokens": tok(s), "audio": None, "duration": None} for s in split_sentences(opt_text)]
        options.append({"idx": i + 1, "sentences": sents})
    return {
        "passageSentences": [],
        "questions": [
            {
                "id": q["id"],
                "answer": q["answer"],
                "stemWord": {"tokens": tok(q["stemWord"]), "audio": None},
                "options": options,
                "explanationZh": q["explanationZh"],
            }
        ],
    }


def block_mondai8(q):
    correct = mondai8_correct_sentence(q["explanationZh"])
    if correct is None:
        print('WARN: 問題8 id' + str(q["id"]) + ' 解析里没找到"正确语序"，stem留空')
    stem = {"tokens": tok(correct), "audio": None, "duration": None} if correct else None
    # stemBlank：框架句本身没有<<...>>标记（转写时没有加），直接整句tokenize，
    # 占位符＿＿＿＿/★原样当普通文字处理，不需要blank token（不涉及剧透）。
    return {
        "passageSentences": [],
        "questions": [
            {
                "id": q["id"],
                "answer": q["answer"],
                "stemBlank": {"tokens": tok(q["stemText"])},
                "stem": stem,
                "options": [option_field(i + 1, o) for i, o in enumerate(q["options"])],
                "explanationZh": q["explanationZh"],
            }
        ],
    }


def block_mondai9(q):
    answer_by_num = {}
    sub_questions = []
    for sq in q["questions"]:
        num = str(sq["id"])
        answer_by_num[num] = sq["options"][sq["answer"] - 1]
        sub_questions.append(sq)
    filled_text = fill_blanks(q["passageText"], answer_by_num)
    questions = []
    for sq in sub_questions:
        questions.append(
            {
                "id": sq["id"],
                "answer": sq["answer"],
                "stemInstruction": "文章中の " + str(sq["id"]) + " に入れるのに最もよいものを、1・2・3・4から一つ選びなさい。",
                "options": [option_field(i + 1, o) for i, o in enumerate(sq["options"])],
                "explanationZh": sq["explanationZh"],
            }
        )
    return {
        "is_mondai9": True,
        "passageSentencesBlank": passage_sentences_with_blanks(q["passageText"]),
        "passageSentences": passage_sentences_plain(filled_text),
        "questions": questions,
    }


def block_reading_single(passage_text, sub_questions):
    """問題10/11/13 共用：一段passage + N道题，题干都是纯问句(stemInstruction)。"""
    questions = []
    for sq in sub_questions:
        questions.append(
            {
                "id": sq["id"],
                "answer": sq["answer"],
                "stemInstruction": sq["stemText"],
                "options": [option_field(i + 1, o) for i, o in enumerate(sq["options"])],
                "explanationZh": sq["explanationZh"],
            }
        )
    return {"passageSentences": passage_sentences_plain(passage_text), "questions": questions}


def block_mondai12(q):
    sentences = (
        [{"tokens": tok("A"), "audio": None, "duration": None}]
        + passage_sentences_plain(q["passageA"])
        + [{"tokens": tok("B"), "audio": None, "duration": None}]
        + passage_sentences_plain(q["passageB"])
    )
    questions = []
    for sq in q["questions"]:
        questions.append(
            {
                "id": sq["id"],
                "answer": sq["answer"],
                "stemInstruction": sq["stemText"],
                "options": [option_field(i + 1, o) for i, o in enumerate(sq["options"])],
                "explanationZh": sq["explanationZh"],
            }
        )
    return {"passageSentences": sentences, "questions": questions}


def block_mondai14(q):
    lines = [ln.strip() for ln in q["documentText"].split("\n") if ln.strip()]
    sentences = [{"tokens": tok(ln), "audio": None, "duration": None} for ln in lines]
    questions = []
    for sq in q["questions"]:
        questions.append(
            {
                "id": sq["id"],
                "answer": sq["answer"],
                "stemInstruction": sq["stemText"],
                "options": [option_field(i + 1, o) for i, o in enumerate(sq["options"])],
                # 問題14没有中文解析，正确答案来自正答表，交卷后只显示选项对错
                "explanationZh": "",
            }
        )
    return {"passageSentences": sentences, "questions": questions}, q["instructionText"]


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    src_dir, out_path = sys.argv[1], sys.argv[2]

    def load(name):
        with open(os.path.join(src_dir, name), encoding="utf-8") as f:
            return json.load(f)

    d15 = load("mondai1-5.json")
    d69 = load("mondai6-9.json")
    d1011 = load("mondai10-11.json")
    d1214 = load("mondai12-14.json")

    mondai_list = []

    # 問題1-5
    by_mondai = {}
    for q in d15:
        by_mondai.setdefault(q["mondai"], []).append(q)
    for m in range(1, 6):
        blocks = [block_simple(q) for q in sorted(by_mondai[m], key=lambda x: x["id"])]
        mondai_list.append({"mondai": m, "label": "問題" + str(m), "instruction": INSTRUCTION[m], "blocks": blocks})

    # 問題6-9
    by_mondai69 = {}
    mondai9_obj = None
    for q in d69:
        if q["mondai"] == 9:
            mondai9_obj = q
        else:
            by_mondai69.setdefault(q["mondai"], []).append(q)
    blocks6 = [block_mondai6(q) for q in sorted(by_mondai69[6], key=lambda x: x["id"])]
    mondai_list.append({"mondai": 6, "label": "問題6", "instruction": INSTRUCTION[6], "blocks": blocks6})
    blocks7 = [block_simple(q) for q in sorted(by_mondai69[7], key=lambda x: x["id"])]
    mondai_list.append({"mondai": 7, "label": "問題7", "instruction": INSTRUCTION[7], "blocks": blocks7})
    blocks8 = [block_mondai8(q) for q in sorted(by_mondai69[8], key=lambda x: x["id"])]
    mondai_list.append({"mondai": 8, "label": "問題8", "instruction": INSTRUCTION[8], "blocks": blocks8})
    mondai_list.append({"mondai": 9, "label": "問題9", "instruction": INSTRUCTION[9], "blocks": [block_mondai9(mondai9_obj)]})

    # 問題10-11
    blocks10 = []
    blocks11 = []
    for q in d1011:
        if q["mondai"] == 10:
            blocks10.append((q["id"], block_reading_single(q["passageText"], [q])))
        elif q["mondai"] == 11:
            first_id = q["questions"][0]["id"]
            blocks11.append((first_id, block_reading_single(q["passageText"], q["questions"])))
    blocks10.sort(key=lambda x: x[0])
    blocks11.sort(key=lambda x: x[0])
    mondai_list.append({"mondai": 10, "label": "問題10", "instruction": INSTRUCTION[10], "blocks": [b for _, b in blocks10]})
    mondai_list.append({"mondai": 11, "label": "問題11", "instruction": INSTRUCTION[11], "blocks": [b for _, b in blocks11]})

    # 問題12-14
    for q in d1214:
        if q["mondai"] == 12:
            mondai_list.append({"mondai": 12, "label": "問題12", "instruction": INSTRUCTION[12], "blocks": [block_mondai12(q)]})
        elif q["mondai"] == 13:
            blk = block_reading_single(q["passageText"], q["questions"])
            mondai_list.append({"mondai": 13, "label": "問題13", "instruction": INSTRUCTION[13], "blocks": [blk]})
        elif q["mondai"] == 14:
            blk, instr = block_mondai14(q)
            mondai_list.append({"mondai": 14, "label": "問題14", "instruction": instr, "blocks": [blk]})

    mondai_list.sort(key=lambda m: m["mondai"])

    data = {
        "title": "N2真题模考：2024年12月 言語知識・読解",
        "mondaiList": mondai_list,
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("window.EXAM_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n")

    total_q = sum(len(b["questions"]) for m in mondai_list for b in m["blocks"])
    print("wrote", out_path)
    print("mondai count:", len(mondai_list), "total questions:", total_q)


if __name__ == "__main__":
    main()
