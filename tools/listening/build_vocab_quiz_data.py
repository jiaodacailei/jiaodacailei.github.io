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

每条输出还带一个 `category` 字段（"dialogue"/"text"/"other"），直接复用
occurrences.json 里人工核实过的 `src`（会话/课文里真实出现的词，已经处理过
活用形不一致的问题，不是重新拿词典基本型去匹配）；走 authored_examples.json
（会话/课文里真没找到）的词条固定是 "other"。前端"单词测试"tab 靠这个字段
把词库分成"会话相关/课文相关/其他"三部分分别测试、各自独立记进度和错题。

<vocab_words.json>：跟 build_vocab_from_wordlist.py 用的是同一份格式，但这里
  只用 id/text/zh/kana 四个字段（audio 路径不需要传，跟 build_page.py 生成
  生词卡片时用的是同一条规则：`audio/seg-{id:03d}.mp3`，由 build_page.py 自己
  拼，不在这份数据里重复）。id 允许带不带 "a" 前缀都行，这里统一转成不带前缀
  的数字字符串再往下用。

  没有 "kana" 字段的词条，读音现在会跟生词卡片显示用的furigana走同一条
  pykakasi 转换（`build_page.py` 的 `ruby_html()`），不是简单退化成 `text`
  本身——**这是修过的一个真实 bug**：之前退化成 `text`，"听音频写假名"/
  "根据中文写假名" 这两类题型对没填 `kana` 的词（大多数词其实都没填，因为
  pykakasi 默认转换已经猜对了，只有猜错的才需要显式填 `kana` 覆盖）判分时，
  标准答案会变成词的原文本身（比如"〜食"）而不是假名（"しょく"），用户怎么
  打都会被判错，"答えを見る"给出的也是错的"答案"。只有真的需要覆盖 pykakasi
  默认读音（比如"〜所"这种多音字，pykakasi 会猜成ところ而不是しょ）的词条
  才必须显式填 `kana`，其余词条不填也能拿到正确读音——但如果这里退化成
  `text` 而不是真的转换一遍，等于所有"没显式填 kana"的词条全部受影响，
  不是只有个别偏门词条才踩坑。

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
import os
import re
import json
import argparse

sys.path.insert(0, os.path.dirname(__file__))
from build_page import _kks, _is_kanji, _TOKEN_READING_OVERRIDES_UNCONDITIONAL, _TOKEN_READING_OVERRIDES_BY_PREV

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def norm_id(raw_id):
    s = str(raw_id)
    return s[1:] if s.startswith("a") else s


_KATAKANA_RUN_RE = re.compile(r"[゠-ヿー]+")


def _kata_run_to_hira(run):
    # 长音符"ー"（U+30FC）片假名/平假名共用同一个字符，不能按平行区块0x60的
    # 固定偏移量去移——那样会移到一个不相干的组合用声调符号上（U+309C，
    # "半浊音符"），不是合法的平假名字符。真实转写产出的平假名结果（比如
    # "ハンバーグ"→"はんばーぐ"）"ー"本来就是原样保留、没有跟着变换的，这里
    # 复现同一条规则，"ー"永远原样返回，只转换真正的片假名字母本身。
    return "".join(
        chr(ord(ch) - 0x60) if "゠" <= ch <= "ヶ" else ch
        for ch in run
    )


def _fix_katakana_in_kana(text, kana):
    """通用版保护，不限于"整个词都是片假名"——"テレビ局""口コミ"这类片假名+
    汉字混合词同样会中招：混合词里片假名部分被连着汉字一起转写成了全平假名
    （比如"テレビ局"被存成"てれびきょく"，正确应该是"テレビきょく"——"局"
    的读音きょく没问题，但"テレビ"不该被转换）。做法：把 text 里每一段连续
    片假名单独转成对应平假名，如果这段平假名确实作为子串出现在 kana 里，
    说明这段片假名被错误转写了，换回原始片假名；只在能精确定位到子串时才
    替换，找不到就不动那一段（保守，不确定就不改，避免误伤真的另有规律的
    读音）。"""
    fixed = kana
    changed = False
    for m in _KATAKANA_RUN_RE.finditer(text):
        run = m.group(0)
        hira_run = _kata_run_to_hira(run)
        if hira_run != run and hira_run in fixed:
            fixed = fixed.replace(hira_run, run, 1)
            changed = True
    return fixed, changed


def kana_for(word):
    """没有显式 kana 覆盖时，走跟生词卡片显示furigana完全同一条转换路径（同一个
    pykakasi 实例 + 同一张手动订正表），不能简单退化成 word["text"] 本身——这是
    之前真实踩过的坑（详见文件头部说明）。

    "〜"是词典抄来的占位符号（不对应实际发音，比如"〜食"读しょく，不读〜しょく），
    转换完之后要去掉，不然"听音频写假名"这类题型会要求用户连这个不发音的符号
    也打出来。"/"表示"二选一"（比如"お/ご〜申し上げる"是"お…申し上げる"或
    "ご…申し上げる"两种说法，不是"お"和"ご"连着念的"おご…"），没法自动算出
    唯一读音，这类词条必须显式提供 kana，这里直接报错提醒，不去猜一个大概率
    错误的拼接结果。"""
    if "kana" in word:
        # 显式提供的 kana 也要过一遍片假名保护——真实踩过的坑（textbook-sjp-
        # zg-l13）：词表来源（这一课走的是不调用 build_vocab_from_wordlist.py
        # 的自定义生词流程）给"ハンバーグ"这类纯片假名词条也无差别填了 kana，
        # 填成了转写出来的平假名"はんばーぐ"，这里直接透传的话，"听音频写
        # 假名"/"根据中文写假名"这两类题型的标准答案会变成平假名——用户照着
        # 原文老老实实打片假名反而被判错。片假名外来语的"假名读音"就是它自己，
        # 不存在另一套平假名读法，显式 kana 如果是纯片假名词条转成的平假名，
        # 直接纠正回原文，不静默保留错误值。这条保护起初只查"整个词是不是纯
        # 片假名"，后来发现"テレビ局""口コミ""キリスト教""排気ガス"这类片假名+
        # 汉字混合词同样会中招（片假名部分单独也被转写成了平假名，汉字部分的
        # 读音反而是对的）——纯片假名只是这类问题的一个特例，`_fix_katakana_
        # in_kana()` 是通用版：不管词里有没有汉字，只要某一段连续片假名被错误
        # 转写成对应平假名、且能在 kana 里精确定位到，就换回来，覆盖两种场景。
        kana = word["kana"]
        # kana 跟 text 一字不差、但 text 含汉字——假名读音不可能跟汉字原文
        # 长得一样，这不是真的读音，几乎一定是数据源头的笔误（真实案例：
        # textbook-sjp-zg-l14"〜次"/"〜未満"两个词条被误填成 kana==text，
        # 这里原来会原样透传，"听音频写假名"/"根据中文写假名"这两类题型的
        # 标准答案因此变成了汉字原文本身，用户不管写什么都不可能判对；同一份
        # 坏 kana 值另外还会传进 `_split_kana_segments()` 让生词卡片完全不
        # 显示furigana，两处是同一个根——见 build_page.py 里同一条检查的
        # 详细说明）。该留空这个字段，不该填成 text 本身。
        if kana == word["text"] and any(_is_kanji(ch) for ch in word["text"]):
            raise ValueError(
                f"词条 {word['text']!r} 的 kana 字段跟 text 完全相同，但 text 含汉字——"
                f"这不是真的读音，多半是笔误，应该留空这个字段让读音走自动转换/订正表"
            )
        fixed_kana, changed = _fix_katakana_in_kana(word["text"], kana)
        if changed:
            print(f"警告：词条 {word['text']!r} 里的片假名部分在显式 kana={kana!r} "
                  f"里被错误转写成了平假名，纠正为 {fixed_kana!r}")
            return fixed_kana
        return kana
    if "/" in word["text"]:
        raise ValueError(
            f"词条 {word['text']!r} 带 '/' 二选一符号（比如敬语'お/ご'前缀），"
            f"没法自动算出唯一读音，必须在 vocab_words.json 里显式给这条填 kana 字段"
        )
    # 跟 ruby_html() 同一条判断：只有含汉字的 token 才用假名读音替换，片假名/
    # 平假名/符号这些 token 原样保留——片假名外来语（比如"スケジュール"）本来
    # 就是用片假名书写/朗读的，不存在另一套"平假名读音"，转成平假名反而是错的
    # （真实踩过：这条改动第一版没加这层判断，把"スケジュール"转成了
    # "すけじゅーる"，"ハード"转成"はーど"，这类片假名词条一次性有10个受影响）。
    tokens = _kks.convert(word["text"])
    parts = []
    prev_orig = None
    for t in tokens:
        orig = t["orig"]
        hira = t["hira"]
        if orig in _TOKEN_READING_OVERRIDES_UNCONDITIONAL:
            hira = _TOKEN_READING_OVERRIDES_UNCONDITIONAL[orig]
        elif (prev_orig, orig) in _TOKEN_READING_OVERRIDES_BY_PREV:
            hira = _TOKEN_READING_OVERRIDES_BY_PREV[(prev_orig, orig)]
        prev_orig = orig
        parts.append(hira if any(_is_kanji(ch) for ch in orig) else orig)
    return "".join(parts).replace("〜", "")


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
        try:
            kana = kana_for(w)
        except ValueError as e:
            print(f"FAIL: word {wid} ({w['text']!r}): {e}")
            sys.exit(1)
        entry = {
            "id": int(wid),
            "text": w["text"],
            "kana": kana,
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
            # "这个词真的出现在会话/课文里"这件事，人工核实 occurrence 的时候已经
            # 判断过一次了（包括处理活用形不一致的问题——blank 存的是这句里实际
            # 出现的活用形，不是词典基本型），单词测试 tab 按"会话相关/课文相关/
            # 其他"分三部分测试时直接复用这个 src，不用另外再猜一遍。
            entry["category"] = o["src"]
        else:
            auth_key = next(k for k in authored if norm_id(k) == wid)
            a = authored[auth_key]
            if a["blank"] not in a["ja"]:
                print(f"FAIL: word {wid} 的 authored blank {a['blank']!r} 不是例句 {a['ja']!r} 的子串")
                sys.exit(1)
            entry["sentence"] = a["ja"]
            entry["sentence_zh"] = a["zh"]
            entry["blank"] = a["blank"]
            # 会话/课文里真没找到这个词才会走到人工补写例句这条路，天然就是
            # "其他"分类（不属于会话，也不属于课文）。
            entry["category"] = "other"
        quiz.append(entry)

    json.dump(quiz, open(args.out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"wrote {len(quiz)} quiz entries to {args.out_json}")


if __name__ == "__main__":
    main()
