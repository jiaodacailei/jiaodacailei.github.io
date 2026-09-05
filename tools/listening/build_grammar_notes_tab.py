# -*- coding: utf-8 -*-
"""用法：
  python build_grammar_notes_tab.py <data.js路径> <content模块.py路径> [--audio-dir <audio目录>]

把教材配套app自己的"语法与表达"tab内容（截图转录）拼成 data.js 能吃的
tab结构，插到"课文"和"生词"之间（跟教材app自己的tab顺序一致：会话|课文|
语法与表达|生词|練習）——`jp-textbook-lesson` skill 的可选扩展步骤，只在
这一课的素材目录里确实有"语法与表达/{会话,课文}"截图时才需要跑，源头案例
见 SKILL.md 的 l17 条目。

<content模块.py>：任意 .py 文件，必须定义两个模块级变量：
  KAISHIWA = [(卡片标题, 中文讲解正文, [例句, ...]), ...]
  KEWEN    = 同上，对应"课文"分组
每条例句是变长 tuple：
  (日语, 中文)                      —— 专题卡（不带编号，比如"称赞・谦虚"
                                       "词语之窗"）用这个，没有挖空/生词联动。
  (日语, 中文, blanks)              —— 编号语法点（"1. 省略主语"这种）用这个，
                                       blanks是这句里要挖空的原文片段列表（跟
                                       截图里加粗那部分逐字对应，必须是"日语"
                                       字符串的精确子串——前端挖空逻辑是纯
                                       indexOf顺序查找，没有模糊匹配）。
  (日语, 中文, blanks, vocab_id)    —— 这句的挖空目标同时也是"生词"tab里的
                                       一个词条（vocab_id是那个词条的id，靠
                                       人工核实，不是自动模糊匹配出来的——很
                                       多语法点本身不是词，"抜きで""ことに"
                                       这类语法结构就没有对应的vocab_id，是
                                       正常情况，不是漏配）。
卡片标题：不带编号的专题卡里的例句不参与下面的"挖空默认联动"逻辑（专题卡
一张卡里塞好几个不同表达，不是"一卡一语法点"的干净结构，没法批量挖空）。

## 三件事，一次跑完

1. **拼"语法与表达"tab**：跟第一版逻辑一样——例句能在现有"会话"/"课文"
   tab里精确文字匹配上的句子（原文一字不差），直接复用那句的tokens/audio
   （含char_times，真人朗读+faster-whisper对齐）；匹配不上的（本课对话/
   课文里没出现过的补充例句）只做`tokenize_ja()`假名注音，不配音频
   （audio=null）。

2. **给会话/课文里的真句子默认加上语法点对应的挖空**：编号语法点的例句如果
   匹配到了会话/课文里的真句子，这句的blanks目标（截图里加粗那部分）会
   追加进那句在"会话"/"课文" tab里自己的`blanks`数组（已有的、来自生词表
   的blanks不动，新目标去重后追加）——这样正常读会话/课文做填空练习时，
   语法点本身也能被挖空考到，不止是生词表挑出来的单词。专题卡的例句不参与
   这一步（没有blanks字段）。

3. **给"生词"tab追加语法例句练习——挂在原卡片自己身上，不再拆成新卡片**：
   编号语法点的例句如果带vocab_id，且这句跟那个词条现在已有的例句（原有
   `quizSentence` + 已经追加过的`moreExamples[].quizSentence`）都不是
   同一句，就追加进`orig["moreExamples"]`（列表，每项
   `{quizSentence, blanks, sentenceAudio}`）——**同一个词永远只有一张
   卡片，`id`/`tokens`/词本身读音`audio`都不变，前端在这一张卡片内部
   渲染出多个例句区块**。早期版本是"追加一张新卡片、复制tokens/audio"，
   真实反馈"投げ込む单词重复了"——同一个词紧挨着出现两次，即使内容上
   没错，观感上像是内容重复，改成挂在同一张卡片下面。如果新例句跟已有
   的（原有的或者moreExamples里任意一条）是同一句，说明没有新增信息，
   跳过、不追加。

   `sentenceAudio`：语法例句如果匹配到了会话/课文的真句子，直接用那句的
   audio；专题卡/新造例句没有对应真实录音，留null。

4. **単語テスト（`DATA.quiz`）继续用独立记录，不跟"生词"tab走同一套
   moreExamples**——quiz引擎（`docs/js/listening-page.js`的
   `TYPES`/`audioSrcFor`）是"一条记录出一组题"的模型，不是"一张卡片"，
   合并进数组对它没有意义。这里还是给每条不重复的语法例句单独插入一条
   新记录（新`id`），`category`不是照抄原词条的category，而是按这句
   语法例句自己的来源判——匹配到会话真句子记"dialogue"，匹配到课文真句子
   记"text"，例句本身是新造的（没匹配上任何真句子）记"other"——因为
   category描述的是"这句例句是不是从本课对话/课文里真实核实过的原句"，
   不是词条本身的属性，同一个词条的两条例句完全可能一条来自真句子、一条
   是补写的。

   `audioSrcFor(word)`只认id推audio路径（`audio/seg-{id:03d}.mp3`），
   新id目前在磁盘上没有对应文件——直接复制原词条自己的
   `audio/seg-{原id:03d}.mp3`到新id那个路径（同一个词的读音，只是换了
   个id用来独立记录进度/错题），这个脚本自己做，不留人工TODO。
   `--audio-dir`不传时默认是`<data.js所在目录>/audio`。

## 重复运行防护

对已经带"语法与表达"tab的data.js重跑会直接报错拒绝，不会静默重复插入/
重复追加生词卡。如果是想改内容，正确做法是回到加这个tab之前的干净版本
（比如用`git show <加tab之前的commit>:<data.js路径>`）重新跑一遍这个脚本，
不要在已经跑过一次的文件上二次运行。
"""
import sys
import os
import re
import json
import shutil
import argparse
import importlib.util

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_page import tokenize_ja, normalize_numbers  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def load_content(path):
    spec = importlib.util.spec_from_file_location("grammar_notes_content", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.KAISHIWA, mod.KEWEN


def load_data(data_js_path):
    raw = open(data_js_path, encoding="utf-8").read()
    prefix = raw[: raw.index("{")]
    body = raw[raw.index("{") :]
    body = re.sub(r";\s*$", "", body.strip())
    data = json.loads(body)
    if any(t["mondai"] == "语法与表达" for t in data["tabs"]):
        raise SystemExit(
            "data.js 里已经有“语法与表达”tab 了——重复跑会再插入一份、"
            "生词卡也会重复追加。如果是想改内容，回到加这个tab之前的干净"
            "版本（比如 git show <早期commit>:<data.js路径>）重新跑一遍，"
            "不要对着已经合并过的文件再跑一次这个脚本。"
        )
    return prefix, data


def build_lookup(data):
    """text -> (tab名, sentence对象引用)。sentence对象是data里的原始dict，
    后面合并blanks是直接在这个dict上原地改，改完随json.dumps一起落地。"""
    lookup = {}
    for tab in data["tabs"]:
        if tab["mondai"] not in ("会话", "课文"):
            continue
        for q in tab["questions"]:
            for s in q["sentences"]:
                text = "".join(t["text"] for t in s["tokens"] if t.get("text") != "\n")
                lookup[text] = (tab["mondai"], s)
    return lookup


def next_id_counter(data):
    max_id = 0
    for tab in data["tabs"]:
        for q in tab["questions"]:
            for s in q["sentences"]:
                max_id = max(max_id, s["id"])
    for item in data.get("quiz", []):
        max_id = max(max_id, item["id"])
    n = [max_id]

    def nxt():
        n[0] += 1
        return n[0]

    return nxt


def merge_blanks(sentence_obj, new_blanks):
    """追加新挖空目标，跳过已经被现有某个blank"覆盖"的——真实案例：生词表
    自己的blanks习惯挖"词+后面一段活用/助词"的整段（比如"たいしたことでは
    ありません"整句都挖掉），语法点自己的目标词往往只是这段里打头的核心词
    （"たいした"），是已有blank的前缀子串。直接原样append会产生一个"找不到
    独立占位"的死数据——前端挖空是按blanks数组顺序、用searchFrom往后顺序
    查找的（见listening-page.js的setupBlankForCard），排在前面的blank把这
    段文字占掉之后，后面这个子串blank在剩余文字里通常再也找不到重复出现的
    位置，静默变成没有任何效果的空目标，不会报错但也不会真的抠出一个空。
    只在新目标完全没有被任何现有blank整段包含时才追加，避免这种"看起来加了
    但其实是废数据"的情况。反过来"新目标更长、现有的是它的子串"这种情况
    这一课没遇到，暂不处理，遇到了再扩展。

    **加完之后必须按新目标在原文里的实际出现位置重新排一遍`blanks`顺序**——
    同一条setupBlankForCard()的searchFrom是单调向后推进的，只要求"按数组
    顺序"，不认"先加的排前面"这种插入顺序。真实bug：语法点的目标词经常
    排在句子靠前的位置（比如"東西南北の棟が…"的"東西南北"在句首），而
    这句原有的（生词表来源的）blank可能排在句子靠后（"庭を中心に"）——
    如果只是无脑append，新目标会被排在已有blank后面、但在原文里的真实
    位置却在前面，导致searchFrom越过它之后再也找不到，新加的这个空
    静默失效（不报错，打开填空模式却看不到）。这一课首次实现时就踩过
    （id34/46/50三句，新加的目标全部因为这个排序问题没生效），必须每次
    append之后都按位置重新排序，不能假设"append顺序=原文顺序"。"""
    existing = sentence_obj.setdefault("blanks", [])
    text = "".join(t["text"] for t in sentence_obj["tokens"] if t.get("text") != "\n")
    for b in new_blanks:
        if b in existing:
            continue
        if any(b in e for e in existing):
            continue
        existing.append(b)
    existing.sort(key=lambda b: text.find(b))


def make_sentence(ex, lookup, next_id, vocab_extensions):
    """ex是变长tuple：(ja, zh) / (ja, zh, blanks) / (ja, zh, blanks, vocab_id)。
    返回(sentence_dict, source)，source是"dialogue"/"text"/"other"，
    分别对应"匹配到会话真句子"/"匹配到课文真句子"/"没匹配上、例句是新造的"
    ——单词测试新记录的category要用这个，不是照抄原词条的category。"""
    ja, zh = ex[0], ex[1]
    blanks = list(ex[2]) if len(ex) >= 3 else []
    vocab_id = ex[3] if len(ex) >= 4 else None

    found = lookup.get(ja)
    sid = next_id()
    if found:
        src_mondai, real_sentence = found
        if blanks:
            merge_blanks(real_sentence, blanks)
        source = "dialogue" if src_mondai == "会话" else "text"
        sentence = {
            "id": sid,
            "speaker": None,
            "speakerKana": None,
            "tokens": real_sentence["tokens"],
            "zh": zh,
            "notes": "",
            "blanks": list(blanks),
            "audio": real_sentence.get("audio"),
        }
    else:
        source = "other"
        sentence = {
            "id": sid,
            "speaker": None,
            "speakerKana": None,
            "tokens": tokenize_ja(ja),
            "zh": zh,
            "notes": "",
            "blanks": list(blanks),
            "audio": None,
        }

    if vocab_id is not None:
        vocab_extensions.append({"vocab_id": vocab_id, "ja": ja, "zh_ignored": zh, "blanks": blanks, "source": source})
        # sentence本身携带的audio既是"这句真句子的audio"也是生词tab新卡要用的
        # sentenceAudio来源，vocab_extensions里额外存一份，避免下面处理时
        # 还要回头重新查一遍lookup。
        vocab_extensions[-1]["sentence_audio"] = sentence.get("audio")

    return sentence, (source != "other")


def build_group(cards, lookup, next_id, stats, vocab_extensions):
    questions = []
    for title, overview, examples in cards:
        sentences = []
        for ex in examples:
            s, matched = make_sentence(ex, lookup, next_id, vocab_extensions)
            sentences.append(s)
            stats["matched" if matched else "new"] += 1
        questions.append({"question": title, "overview": overview, "answer": "", "sentences": sentences})
    return questions


def apply_vocab_extensions(data, vocab_extensions, next_id, stats):
    vocab_tab = next(t for t in data["tabs"] if t["mondai"] == "生词")
    # id -> question字典引用（只存question，不存下标——下标会被前面插入的新
    # 卡顶掉变得不准，真实踩过这个坑：同一个question列表里先给id59插入
    # 一张新卡，后面同一个列表里id63的原始下标就整体错位了1个位置，
    # `q["sentences"][base_idx]`会取到别的词条而不是id63自己，误判"跟原有
    # 例句不一样"从而错误追加。改成每次都按id现查当前位置，不用缓存的下标。
    vocab_question_of = {}
    for q in vocab_tab["questions"]:
        for s in q["sentences"]:
            vocab_question_of[s["id"]] = q

    def find_index(seq, target_id):
        for i, s in enumerate(seq):
            if s["id"] == target_id:
                return i
        raise SystemExit(f"vocab_id={target_id}在它所属的question里现查不到了，数据被改坏了。")

    quiz_list = data.setdefault("quiz", [])
    quiz_index = {item["id"]: i for i, item in enumerate(quiz_list)}

    audio_copies = []  # [(src_id, dst_id), ...]，最后统一做文件复制

    # 按vocab_id分组，同一个词多条新例句要按原始顺序依次追加在原词条后面，
    # 不能后加的先插进去、把顺序倒过来。
    from collections import OrderedDict
    grouped = OrderedDict()
    for ext in vocab_extensions:
        grouped.setdefault(ext["vocab_id"], []).append(ext)

    for vocab_id, exts in grouped.items():
        if vocab_id not in vocab_question_of:
            raise SystemExit(f"content模块里写的vocab_id={vocab_id}在'生词'tab里找不到，核对一下这个id对不对。")
        q = vocab_question_of[vocab_id]
        base_idx = find_index(q["sentences"], vocab_id)
        orig = q["sentences"][base_idx]
        # 不再拆成多张卡片——同一个词的额外例句挂在原卡片自己的
        # moreExamples数组里（每条{quizSentence,blanks,sentenceAudio}），
        # 前端一张卡片内渲染成多个.seg-example块，不再是"同一个词连续
        # 出现两次"（真实反馈"投げ込む单词重复了"）。原卡片的id/tokens/
        # audio（词本身的读音）完全不动，moreExamples只追加不覆盖已有的。
        more_examples = orig.setdefault("moreExamples", [])
        existing_sentences = {orig.get("quizSentence")} | {e["quizSentence"] for e in more_examples}
        for ext in exts:
            if ext["ja"] in existing_sentences:
                stats["vocab_skip_identical"] += 1
                continue
            more_examples.append({
                "quizSentence": ext["ja"],
                "blanks": list(ext["blanks"]),
                "sentenceAudio": ext.get("sentence_audio"),
            })
            existing_sentences.add(ext["ja"])
            stats["vocab_added_to_wordlist"] += 1

            if vocab_id in quiz_index:
                orig_quiz = quiz_list[quiz_index[vocab_id]]
                if orig_quiz.get("sentence") == ext["ja"]:
                    stats["quiz_skip_identical"] += 1
                else:
                    # 単語テスト这边仍然是"一条记录一道题"的模型（quiz引擎
                    # 假设一词一句，见listening-page.js的TYPES/audioSrcFor），
                    # 跟"生词"tab那边合并进moreExamples不是一回事，这里继续
                    # 用独立id+独立记录，音频也还是复制一份到这个新id。
                    new_quiz_id = next_id()
                    new_quiz_entry = {
                        "id": new_quiz_id,
                        "text": orig_quiz["text"],
                        "kana": orig_quiz["kana"],
                        "zh": orig_quiz["zh"],
                        "sentence": ext["ja"],
                        "sentence_zh": ext["zh_ignored"],
                        "blank": ext["blanks"][0] if ext["blanks"] else "",
                        "category": ext["source"],
                    }
                    orig_qidx = quiz_index[vocab_id]
                    quiz_list.insert(orig_qidx + 1, new_quiz_entry)
                    # 后面的下标全部要+1，重建一次索引避免用旧下标插错位置
                    quiz_index = {item["id"]: i for i, item in enumerate(quiz_list)}
                    audio_copies.append((vocab_id, new_quiz_id))
                    stats["quiz_added"] += 1
            else:
                stats["quiz_missing_original"] += 1

    return audio_copies


def copy_audio_files(audio_dir, audio_copies, stats):
    for src_id, dst_id in audio_copies:
        src_path = os.path.join(audio_dir, "seg-{:03d}.mp3".format(src_id))
        dst_path = os.path.join(audio_dir, "seg-{:03d}.mp3".format(dst_id))
        if not os.path.exists(src_path):
            print(f"WARNING: 源音频不存在，跳过复制: {src_path}")
            continue
        shutil.copyfile(src_path, dst_path)
        stats["audio_files_copied"] += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_js")
    ap.add_argument("content_path")
    ap.add_argument("--audio-dir", default=None)
    args = ap.parse_args()

    audio_dir = args.audio_dir or os.path.join(os.path.dirname(os.path.abspath(args.data_js)), "audio")

    kaishiwa, kewen = load_content(args.content_path)
    prefix, data = load_data(args.data_js)
    lookup = build_lookup(data)
    next_id = next_id_counter(data)

    stats = {
        "matched": 0, "new": 0,
        "vocab_added_to_wordlist": 0, "vocab_skip_identical": 0,
        "quiz_added": 0, "quiz_skip_identical": 0, "quiz_missing_original": 0,
        "audio_files_copied": 0,
    }
    vocab_extensions = []
    questions = []
    questions.append({"question": "会话", "overview": "", "answer": "", "sentences": []})
    questions.extend(build_group(kaishiwa, lookup, next_id, stats, vocab_extensions))
    questions.append({"question": "课文", "overview": "", "answer": "", "sentences": []})
    questions.extend(build_group(kewen, lookup, next_id, stats, vocab_extensions))

    grammar_tab = {"mondai": "语法与表达", "questions": questions}
    idx = next(i for i, t in enumerate(data["tabs"]) if t["mondai"] == "生词")
    data["tabs"].insert(idx, grammar_tab)

    audio_copies = apply_vocab_extensions(data, vocab_extensions, next_id, stats)
    copy_audio_files(audio_dir, audio_copies, stats)

    out = prefix + json.dumps(normalize_numbers(data), ensure_ascii=False, indent=2) + ";\n"
    with open(args.data_js, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)

    print("matched (reused audio):", stats["matched"])
    print("new (no audio, tokenize_ja only):", stats["new"])
    print("vocab: added to 生词tab:", stats["vocab_added_to_wordlist"],
          "| skipped (identical to existing example):", stats["vocab_skip_identical"])
    print("单词测试: added:", stats["quiz_added"],
          "| skipped (identical):", stats["quiz_skip_identical"],
          "| original quiz entry missing:", stats["quiz_missing_original"])
    print("audio files copied:", stats["audio_files_copied"])
    print("wrote", args.data_js)


if __name__ == "__main__":
    main()
