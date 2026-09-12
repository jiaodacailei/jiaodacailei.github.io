# -*- coding: utf-8 -*-
"""用法：
  python build_n2_reference_page.py <out_dir> <content_module.py>
      --title T [--password P | --password-hash H] [--tab-label L]

给"N2语法"/"N2词汇"这类**没有配套录音、持续按单元增长**的参考资料页面用
（jp-n2-grammar-page/jp-n2-vocab-page 两个 skill 共用同一个脚本，内容
形状足够接近：一个"知识点"tab——语法点或者单词条目，都是"标题+讲解+若干
例句"——加一个"练习"tab，教材原版四选一题目）。

跟 jp-textbook-lesson 系列课文页最大的不同：例句没有真人朗读，全部用
edge-tts（ja-JP-NanamiNeural，跟 build_exam_audio.py/build_grammar_
notes_audio.py 同一个 voice）合成 + faster-whisper 对齐拿 char_times，
每句独立成一个 TTS 音频文件（不是从一段长录音里切出来的，span_start
固定是0，不需要 refine_boundaries.py 那套"多句边界怎么切"的逻辑）。

**内容模块（增量真相源）**：每次运行都要传全量内容（不是"这次只传新增的
一个单元"），已经合成过音频的句子会跳过重新合成（判断依据是
audio/seg-{id:03d}.mp3 是否已存在，不是靠 data.js 里的标记，可以放心
重复整体重新跑）——以后要加新单元，直接在内容模块里追加，不用管以前
跑过的单元，脚本自己认得出哪些已经处理过。id 用"整个内容模块里，句子/
MCQ题目各自的出现顺序"分配，不能中途在数组中间插入旧单元的新内容
（会导致后面所有id集体错位、旧音频文件全部对不上），只能在数组末尾追加
新单元。

<content_module.py> 必须定义两个模块级变量：
  UNITS = [
    {
      "label": "第1单元",       # 对应 data.js 的 question 分组标题
      "points": [
        {
          "title": "1. ～あげく(に)",   # 卡片标题
          "overview": "接续：……\\n说明：……\\n注意：……",  # 中文讲解，
              # 换行用 \\n，页面按 white-space:pre-line 显示
          "examples": [
            ("……。", "……译文……"),  # (日语, 中文) 二元组，跟 l17/l18
                # "语法与表达"专题卡的例句格式一致——这里全部都要TTS配音，
                # 不存在"匹配不上真句子"这回事（没有真句子可匹配）
            ("……。", "……译文……", ["挖空片段1", "挖空片段2"]),  # 第三个
                # 元素可选：填空练习模式要挖空的原文片段列表，每个必须是
                # 第一个元素（日语原文）的字面子串，缺省当[]（不给填空）
          ],
        },
        {
          # 一个语法点有多个"接续"时（书上"接続1/接続2"或"①②"，各自带
          # 独立的说明+△例句），用 groups 代替上面的 overview/examples，
          # 每组各自一份完整的"接续/说明/注意"文字+这组自己的examples——
          # 渲染时按顺序"这组的文字块→这组的例句卡片→下组的文字块→…"，
          # 不会把不同接续的例句混在一起平铺。只有一种接续的点继续用
          # 上面的写法，两种写法可以在同一个UNITS里混用。
          "title": "6. ～上で(は)",
          "groups": [
            {
              "overview": "接续1：……\\n说明1：……\\n注意1：……",
              "examples": [("……。", "……译文……"), ...],
            },
            {
              "overview": "接续2：……\\n说明2：……\\n注意2：……",
              "examples": [("……。", "……译文……"), ...],
            },
          ],
        },
        ...
      ],
    },
    ...
  ]
  MCQ_UNITS = [
    {
      "label": "第1单元",
      "questions": [
        {
          "stem": "ここ数年，日本へ留学する学生は（___）一方だ。",  # 用
              # 半角"（___）"（三个下划线）标记空位，不是全角"＿＿＿＿"——
              # tokenize_ja()对下划线本身处理没问题，用这个记号纯粹是
              # 作者写起来方便，脚本会替换成真正的挖空token
          "options": ["増え", "増える", "増やす", "増やし"],  # 字符串
              # 列表，索引0对应教材选项"1"，不需要显式idx字段
          "answer": 2,        # 正确选项的编号（1-based，跟教材一致）
          "explanation": "",  # 可选，中文解析，没有就留空字符串
        },
        ...
      ],
    },
    ...
  ]
"""
import sys
import os
import re
import json
import html
import hashlib
import asyncio
import argparse
import tempfile
import subprocess
import importlib.util

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_page import (  # noqa: E402
    tokenize_ja, normalize_numbers, build_lesson_data, SHELL_TEMPLATE,
)
from refine_boundaries import align_group  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VOICE = "ja-JP-NanamiNeural"
BLANK_MARKER_RE = re.compile(r"（___）|\(___\)|___")


def load_content(path):
    spec = importlib.util.spec_from_file_location("n2_reference_content", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.UNITS, getattr(mod, "MCQ_UNITS", [])


async def _synth(text, out_path):
    import edge_tts
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(out_path)


def synth_tts(text, out_path):
    asyncio.run(_synth(text, out_path))


# TTS多音字读错人工订正表——某些汉字有多个读音，edge-tts偶尔会选错（真实
# 反馈"町的音频中发音是chou，应该是machi哟"："町でお祭りがあって..."这句
# 里"町"该读"まち"，TTS却读成了行政区划/地名常用的"ちょう"）。这里替换的
# 是"喂给TTS合成引擎的文本"，不改变实际存储/显示的原文——原文怎么写、
# 假名怎么标注都不受影响；whisper对齐也仍然拿原文（含汉字）当目标文本，
# 因为对齐本来就是按读音模糊匹配、不是逐字符比对，文本换成假名一样能对
# 上（而且应该对得更准，因为音频这下真读对了）。没法穷举所有多音字提前
# 订正，只能"听到读错的就加一条"，key 特意带上一点上下文（"町で"而不是
# 光"町"）——"町"单独出现在其它词里（比如"○○町"这种地名后缀）读"ちょう"
# 才是对的，不能不分场合把所有"町"都替换成"まち"。
TTS_READING_OVERRIDES = {
    "町で": "まちで",
    # "扇ぐ"（あおぐ，用扇子扇风）孤立成词/词条标题本身没有上下文，
    # edge-tts容易按"扇"字更常见的音读（扇子せんす/扇風機せんぷうき）
    # 猜成せん系读音——真实反馈"扇ぐ（あおぐ），音频的发音不对哟"。
    # 只替换"扇ぐ"这两个字的literal组合（不会误伤"扇子"，那是"扇"+"子"
    # 两个不同字符），词条标题"扇ぐ"和例句"扇子で扇ぐ。"里的"扇ぐ"都会
    # 走到这条替换。
    "扇ぐ": "あおぐ",
}


def apply_tts_reading_overrides(text):
    for kanji, kana in TTS_READING_OVERRIDES.items():
        text = text.replace(kanji, kana)
    return text


def probe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    try:
        return round(float(r.stdout.strip()), 3)
    except ValueError:
        return None


def whisper_align(model, wav_path, text):
    segments, _ = model.transcribe(
        wav_path, language="ja", word_timestamps=True, beam_size=5,
        condition_on_previous_text=False,
    )
    words = []
    for seg in segments:
        if seg.words:
            words.extend(seg.words)
    if not words:
        return None
    _split, char_times_per_sentence, _edge_start, _edge_end = align_group(
        [{"text": text}], words, 0.0
    )
    if char_times_per_sentence is None:
        return None
    return char_times_per_sentence[0]


def synth_and_align(model, text, audio_dir, seg_id, tmp_wav, stats):
    """合成+对齐一句话，返回(audio_rel_filename, duration, char_times)。
    已经合成过（音频文件已存在）就跳过TTS这一步，仍然会重新对齐一遍
    ——对齐结果不落盘在别处，每次跑都要现算，重新算一遍比维护一份
    "对齐结果缓存"简单，faster-whisper跑一句几秒钟，量级上不需要省这个。"""
    filename = "seg-{:03d}.mp3".format(seg_id)
    out_path = os.path.join(audio_dir, filename)
    if not os.path.exists(out_path):
        try:
            synth_tts(apply_tts_reading_overrides(text), out_path)
        except Exception as e:
            print(f"[id={seg_id}] TTS FAILED: {e}")
            stats["failed"] += 1
            return None, None, None

    duration = probe_duration(out_path)
    subprocess.run(
        ["ffmpeg", "-y", "-i", out_path, "-ar", "16000", "-ac", "1", tmp_wav],
        capture_output=True,
    )
    char_times = whisper_align(model, tmp_wav, text)
    if char_times is None:
        stats["fallback"] += 1
        n = len(text)
        if duration and n > 0:
            char_times = [round(duration * k / n, 2) for k in range(n)]
    else:
        stats["ok"] += 1
    return filename, duration, char_times


_WORD_NUM_PREFIX_RE = re.compile(r"^\d+\.\s*")
_WORD_TRAILING_FULLWIDTH_PAREN_RE = re.compile(r"（[^（）]*）$")


def word_answer_text(title):
    """从标题原文抽出"这个词/语法点本身该怎么读"——跟 listening-page.js
    里 extractTitleAnswer() 完全同一条规则（去掉编号前缀，去掉结尾的全角
    括注），两处独立各写一份是因为一个跑在Python构建期、一个跑在浏览器里，
    没有共享模块的机制，规则改动要记得两边一起改。"""
    return _WORD_TRAILING_FULLWIDTH_PAREN_RE.sub(
        "", _WORD_NUM_PREFIX_RE.sub("", title)
    ).strip()


def synth_word_audio(text, audio_dir, word_id, stats):
    """给词条/语法点标题本身合成一份"单独读这个词"的音频——跟例句音频是
    两回事：例句要跟读高亮，得跑whisper对齐拿char_times；这个只是点一下
    听发音，不需要逐字时间戳，纯TTS，省掉对齐这一步（不需要model/tmp_wav
    参数）。文件名前缀"word-"跟例句的"seg-"分开一套独立编号，不共用同一个
    计数器——例句以后可能因为某条目新增/去掉某句例句而不再对齐，词audio
    的编号只跟"点"的出现顺序有关，两套编号各自独立递增，互不干扰。"""
    filename = "word-{:03d}.mp3".format(word_id)
    out_path = os.path.join(audio_dir, filename)
    if not os.path.exists(out_path):
        try:
            synth_tts(apply_tts_reading_overrides(text), out_path)
        except Exception as e:
            print(f"[word_id={word_id}] 单词发音TTS FAILED: {e}")
            stats["word_failed"] = stats.get("word_failed", 0) + 1
            return None
    return filename


def build_point_sentences(units, model, audio_dir, tmp_wav, stats, mondai_label):
    """把 UNITS 展开成 build_lesson_data() 要的 (sentences, questions) 扁平
    列表——跟 l17/l18"语法与表达"tab 的数据形状完全一致，每个语法点/单词
    条目是一个"question"，它的例句是这个question底下的sentences。

    一个语法点如果有多个接续（`point["groups"]`，见脚本开头docstring），
    每组自己的例句照样走seg_id全局递增+TTS/对齐这一套（组与组之间共用
    同一个计数器，不是各自从1开始），只是额外把每组的seg_id列表记进
    `question["groups"]`（`[{"overview": 这组自己的文字, "ids": [seg_id,...]}]`），
    供 build_lesson_data() 按组切分渲染，而不是像普通点那样直接平铺进
    `sentences`。没有 groups 的点完全不受影响，走原来的逻辑。"""
    sentences = []
    questions = []
    seg_id = 0
    word_id = 0

    def synth_examples(examples, question_label):
        nonlocal seg_id
        ids = []
        for example in examples:
            ja, zh = example[0], example[1]
            blanks = example[2] if len(example) > 2 else []
            seg_id += 1
            filename, duration, char_times = synth_and_align(
                model, ja, audio_dir, seg_id, tmp_wav, stats
            )
            if filename is None:
                continue
            sentences.append({
                "id": seg_id, "mondai": mondai_label, "question": question_label,
                "text": ja, "zh": zh, "notes": "", "blanks": blanks,
                "start": 0.0, "char_times": char_times,
            })
            ids.append(seg_id)
        return ids

    for unit in units:
        unit_label = unit.get("label", "")
        for point in unit["points"]:
            question_label = point["title"]
            word_id += 1
            word_text = word_answer_text(question_label)
            # 词条标题本身带"/"或"／"（一个词两种写法，比如"暖か/温か"）时，
            # 不能把这段原样喂给TTS——真实反馈"暖か/温か的发音是
            # atatakanaatataka，应该是atataka吧"：TTS会把两种写法都当成
            # 独立文字念一遍，读成"两遍读音拼在一起"，不是"/"本身被念出来
            # 那么简单。这种情况改喂derive_reading()已经推导出的那份唯一
            # 权威读音（对这条就是纯假名"あたたか"），跟着音发音不会有歧义；
            # 没有"/"的词条不受影响，继续用原来的word_text（保留汉字喂给
            # TTS，让它自己按汉字选读音，多音字读错的个例走
            # TTS_READING_OVERRIDES单独订正，不在这里放大整改范围）。
            word_tts_text = derive_reading(question_label, word_text) if ("/" in word_text or "／" in word_text) else word_text
            word_audio = synth_word_audio(word_tts_text, audio_dir, word_id, stats) if word_text else None
            groups = point.get("groups")
            if groups:
                group_meta = [
                    {"overview": g.get("overview", ""),
                     "ids": synth_examples(g["examples"], question_label)}
                    for g in groups
                ]
                questions.append({
                    "mondai": mondai_label, "question": question_label,
                    "overview": "\n\n".join(g.get("overview", "") for g in groups),
                    "answer": "", "unit": unit_label, "wordAudio": word_audio,
                    "groups": group_meta,
                })
            else:
                synth_examples(point["examples"], question_label)
                questions.append({
                    "mondai": mondai_label, "question": question_label,
                    "overview": point.get("overview", ""), "answer": "",
                    "unit": unit_label, "wordAudio": word_audio,
                })
    return sentences, questions


_TRAILING_PAREN_CONTENT_RE = re.compile(r"（([^（）]*)）$")
_KANA_ONLY_RE = re.compile(r"^[぀-ゟ゠-ヿー・～]+$")
_POS_TAG_RE = re.compile(r"^\[[^\]]*\]\s*")


def derive_reading(title, word_text):
    """给"单词测试"tab的audio2kana/zh2kana两道题型推读音——词条标题结尾的
    全角括注，如果整段内容本身就是纯假名（"（あいかわらず）"这种），那就是
    读音；如果不是纯假名（"（iron）"这种英文词源提示，不是读音），说明这个
    词本身已经是假名了（外来语片假名词自己就能读，标题结尾的英文纯粹是
    给人看词源用的），读音就是word_text本身。"多个写法用"/"或"／"分隔"
    （"アイデア/アイディア"半角、"いざとなると／いざとなれば／
    いざとなったら"全角，两种都出现过）这种取第一个当权威读音，不需要
    全部都收——真实反馈"0118. いざとなると／いざとなれば／いざとなったら"
    这条audio2kana/zh2kana的答案检查发现，之前只按半角"/"切分，这条词
    整段没有末尾读音括注（本身已经是纯假名，不需要另外标注读音）又用的是
    全角"／"分隔三种写法，两次判断都没生效，"kana"直接变成了三种写法
    原样拼在一起的完整字符串，用户不可能打对这种答案。改成同时按半角/
    全角两种斜杠切分，不区分标题实际用的是哪一种。"""
    m = _TRAILING_PAREN_CONTENT_RE.search(_WORD_NUM_PREFIX_RE.sub("", title))
    if m and _KANA_ONLY_RE.match(m.group(1)):
        return m.group(1)
    return re.split(r"[/／]", word_text)[0].strip("～")


def quiz_zh_text(overview):
    """"单词测试"tab的ja2zh/zh2kana两道题型要用的干净中文释义——只取
    overview第一行、去掉开头的"[词性]"标签（跟词典抄来的标注一样，不算
    释义内容本身，来源见 listening-page.js 里 POS_RE 同一条逻辑，这里独立
    写一份是因为这边是Python、那边是JS，没有共享模块的机制）。"""
    first_line = (overview or "").split("\n")[0]
    return _POS_TAG_RE.sub("", first_line).strip()


def chunk_group_sizes(n, size=10, min_last=5):
    """跟 build_exam_vocab.py 的同名函数完全一样的算法（这里独立复制一份，
    两个脚本没有共享模块的机制）：把n个词按size一组切页，最后一组如果
    小于min_last就并进上一组。真实反馈"如果最后一组少于5个，就合到上一组
    吧"——先在N2真题模考的单词测试分类上用过一次，这次是"单词测试"分类
    和侧栏导航分组（page-renderer.js里的chunkGroupSizes，JS单独一份）
    两个新场景复用同一条规则。"""
    if n <= 0:
        return []
    if n <= size:
        return [n]
    full, rem = divmod(n, size)
    if rem == 0:
        return [size] * full
    if rem < min_last:
        return [size] * (full - 1) + [size + rem]
    return [size] * full + [rem]


def build_vocab_quiz_items(units):
    """把 UNITS 展开成"单词测试"tab（跟l17/l18等教材课同一套引擎，
    listening-page.js里读#vocab-quiz-data的那个IIFE）要吃的数据——
    每个词条一条，{id, text, kana, zh, sentences, category, unit, audio}。
    `sentences`是一个列表，每条`examples`（只要能凑出有效blank）对应列表
    里一个{sentence, sentence_zh, blank}——真实反馈"填空题使用例句，如果
    有多个则有多题"：一个词有几条例句，前端就出几道独立的填空题（各自
    单独记错题/进度），不再像旧版那样只挑examples[0]生成唯一一道。旧版
    单条sentence/sentence_zh/blank字段就此废弃（listening-page.js改成读
    sentences数组；教材课build_vocab_quiz_data.py/N2真题build_exam_vocab.py
    这两个姊妹脚本还没跟着改，继续产出旧的单条字段，前端两种形状都认，
    不冲突）。

    这套引擎的"填空"题型对sentence/blank没有任何兜底，字段缺失或者blank
    不是sentence的字面子串会直接在前端崩掉，所以这里发现任何一条例句凑不出
    有效blank，就让这个词整体硬失败（报出所有问题词），不悄悄只丢那一条
    例句——内容模块（n2_vocab_content.py）必须保证每个词至少有一条例句、
    每条例句要么word_text本身就是字面子串，要么examples自己的第三元素
    （`blanks`，跟"生词"tab填空模式共用的那套三元组格式）给出了实际出现
    的形态，要么（只对examples[0]）显式给了quiz_blank覆盖字段。

    category是"组N"，在每个单元内部各自重新分组（不同单元的"组1"是完全
    不同的一批词）——真实反馈"选中某单元，单词测试也只测那个单元，但是
    也要按照单词的分组来切"，组距跟侧栏导航分组用同一个size=10/
    min_last=5，两处看到的"组1"范围因此是一致的。unit字段单独保留（不
    只靠category区分），供前端顶部"单元选择"下拉框先按单元筛一遍词表、
    再在筛出来的子集里重新算这个单元自己的"组N"选项。

    词条如果在 `point["related"]` 里登记了近义词/反义词（`[{relation, text,
    kana, zh}, ...]`，`relation`是"反义词"/"同义词"/"类义词"这种关系标签，
    其余三个字段是那个参照词自己的原文/读音/中文释义——跟 overview 里给人看
    的自由文本注释是两份独立数据，不是解析 overview 反推出来的，这份是专门
    给单词测试用的结构化字段），每条 `related` 会额外生成一条`kind":"related"`
    的 pseudo-word 条目（`{id, kind, mainText, relation, text, zh, category,
    unit}`，没有`sentences`/`kana`/`audio`——不需要，这类题不读音频也不用
    例句）——真实反馈"如果提到近义词或者反义词，需要在单词测试中增加相应
    近义词或者反义词填空"，进一步澄清"不是写假名，而是日文"：`listening-
    page.js`只给`kind=="related"`的条目出**一道**新题型"related"（题面是
    "「主词」的反义词/同义词/类义词是？"+中文释义提示，答案是`text`本身，
    不是`kana`），不跟`blank`/`audio2kana`/`zh2kana`/`ja2zh`那四种题型混在
    一起——这类参照词本身没有独立的读音/例句/音频数据（overview里的注释
    只给了"词+读音+释义"三项，比正常词条缺少例句和TTS音频），达不到常规
    四种题型的数据要求，所以另开一种不依赖音频/例句的新题型，而不是勉强
    把参照词也套进`build_point_sentences()`那条常规词条流水线（会需要现造
    一条例句、重新合成音频，改动范围大得多，用户明确说"不用例句，测法
    不同"）。

    "id"字段特意加了个很大的偏移量（QUIZ_ID_OFFSET）——真实踩过的坑：
    build_page.py 的 sentence_to_data() 里有一段"生词卡片没有自己的
    blanks时，从quiz_by_id按相同id借一份填空例句"的逻辑（专为"生词卡片
    本身只有孤立一个词、没有上下文"这种情况设计的），quiz_by_id是直接拿
    quiz_data的"id"字段当key，如果这里的id也从1开始编号，会跟句子自己的
    seg_id（build_point_sentences()里按例句出现顺序编的，同样从1开始）
    发生大量偶然撞车——句子seg_id=5如果刚好等于某个不相关单词的单词测试
    id=5，这句原本自己就有真实例句的生词卡片会被错误地整个替换成那个
    不相关单词的填空例句。N2词汇每个词现在都有自己真实的例句（fork已经
    把21个空例句的词全部补上），根本不需要"借用"这个机制，加偏移量让两边
    id永远不可能撞上是最简单可靠的隔离办法。音频文件名不用这个偏移后的
    id（要跟build_point_sentences()里synth_word_audio()用的word_id对上，
    那边没有偏移），单独留一个word_id变量。"""
    QUIZ_ID_OFFSET = 1000000
    RELATED_ID_OFFSET = 2000000
    items = []
    word_id = 0
    related_id = 0
    problems = []
    for unit in units:
        unit_label = unit.get("label", "")
        group_sizes = chunk_group_sizes(len(unit["points"]))
        group_labels = []
        for gi, gsize in enumerate(group_sizes, 1):
            group_labels.extend([f"组{gi}"] * gsize)
        for point, group_label in zip(unit["points"], group_labels):
            word_id += 1
            title = point["title"]
            word_text = word_answer_text(title)
            kana = derive_reading(title, word_text)
            zh = quiz_zh_text(point.get("overview", ""))
            examples = point.get("examples") or []
            if not examples:
                problems.append(f"{title}: 没有例句")
                continue
            sentences = []
            word_failed = False
            for i, ex in enumerate(examples):
                ja, zh_sentence = ex[0], ex[1]
                ex_blanks = ex[2] if len(ex) > 2 else None
                blank = ex_blanks[0] if ex_blanks else None
                if not blank and i == 0:
                    blank = point.get("quiz_blank")
                if not blank:
                    for alt in word_text.split("/"):
                        alt = alt.strip("～")
                        if alt and alt in ja:
                            blank = alt
                            break
                if not blank or blank not in ja:
                    problems.append(f"{title}: 第{i + 1}条例句 {ja!r} 里找不到有效的挖空"
                                     f"片段（blank={blank!r}），需要补 blanks/quiz_blank 字段")
                    word_failed = True
                    continue
                sentences.append({"sentence": ja, "sentence_zh": zh_sentence, "blank": blank})
            if word_failed:
                continue
            items.append({
                "id": QUIZ_ID_OFFSET + word_id, "text": word_text, "kana": kana, "zh": zh,
                "sentences": sentences,
                "category": group_label, "unit": unit_label,
                "audio": f"audio/word-{word_id:03d}.mp3",
            })
            for rel in point.get("related") or []:
                related_id += 1
                items.append({
                    "id": RELATED_ID_OFFSET + related_id, "kind": "related",
                    "mainText": word_text, "relation": rel["relation"],
                    "text": rel["text"], "zh": rel["zh"],
                    "category": group_label, "unit": unit_label,
                })
    if problems:
        print("FAIL: 以下词条无法生成单词测试数据：")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    return items


def build_mcq_items(mcq_units):
    """把 MCQ_UNITS 展开成 mcq-quiz.js 要吃的扁平JSON数组——纯文本注音，
    不配TTS音频（教材原版这几种题型本身就是阅读/语法判断题，不是听力题，
    用户没有提出"练习题也要能听"的需求，跟语法点/单词条目的例句音频是
    两回事，不能因为"反正都要tokenize_ja()"就顺手也配一份不需要的音频）。

    `q["answer"]`可以是单个idx，也可以是idx列表（真实案例：N2语法01
    "パートI問題2"词库选择题，参考答案页13/20两题标的是"F/H"，两个语法点
    在那个语境下都讲得通，原样传给mcq-quiz.js，判分时按"是否在列表里"
    处理，这里不用拆分/特殊处理）。

    `q["kind"]=="complete"`（书上没给选项、只给参考例句的自由续写题）没有
    `options`/`answer`，不生成这两个字段，改传`referenceJa`（参考答案原文，
    用于精确匹配判分）+`referenceHintZh`（填空括号里显示的中文提示，
    真实反馈"不需要自评按钮，填空后面加括号显示中文提示，用户输入答案后
    直接根据答案判断对错"——不再是自评，mcq-quiz.js把用户输入跟
    referenceJa做归一化精确匹配自动判分，不需要用户自己点"答对了/答错了"）。

    `q["kind"]=="passage"`（一段短文里同时挖好几个空，每空四选一，比如
    N2语法01"パートⅡ問題3"）——真实反馈"不能分拆成好几道题，应该按照
    原资料，几道题同时展示出来，一起答"，原书本来就是"一段文章、几个
    编号空位、底下分别给各自的四个选项"这种一次性作答的呈现方式，拆成
    独立题目会打散阅读语境。`q["blanks"]`是一个列表，每项
    `{label, options, answer, explanation}`（label是原书上的题号，比如
    "18"，不是从1开始重新编号）；`q["stem"]`里每个空位置写一个"___"
    占位符，占位符出现次数必须跟`len(q["blanks"])`一致，按各自在文中
    出现的顺序一一对应第几个blanks条目——用`BLANK_MARKER_RE.split()`
    切出所有空位（不只是第一个），每个空的显示文字直接用它自己的
    `label`（比如"18"），不是统一显示"____"，前端靠这个数字知道当前
    高亮的是原书哪一题。整段只算queue里的**一个**条目——五个空全部
    答对才算这道题过关，只要有一个错就整段重新塞回队尾重考（不是错哪个
    空只重考那一个），跟原书"这几道题共享同一篇短文"的出题精神一致。
    `explanationZh`自动拼接成每个空各自的解析（带label前缀），不需要
    在`q`里单独再写一份总解析。"""
    items = []
    mcq_id = 0
    for unit in mcq_units:
        for q in unit["questions"]:
            mcq_id += 1
            kind = q.get("kind")
            if kind == "passage":
                parts = BLANK_MARKER_RE.split(q["stem"])
                blanks = q["blanks"]
                if len(parts) - 1 != len(blanks):
                    raise ValueError(
                        f"passage题 id={mcq_id}：stem里的___占位符数量"
                        f"（{len(parts) - 1}）跟blanks条目数（{len(blanks)}）对不上"
                    )
                stem_tokens = []
                for i, part in enumerate(parts):
                    stem_tokens += tokenize_ja(part)
                    if i < len(blanks):
                        stem_tokens.append({"text": f"【{blanks[i]['label']}】", "blank": True})
                items.append({
                    "id": mcq_id, "category": unit["label"], "kind": "passage",
                    "stemTokens": stem_tokens,
                    "blanks": [
                        {
                            "label": b["label"],
                            "options": [
                                {"idx": i + 1, "tokens": tokenize_ja(opt)}
                                for i, opt in enumerate(b["options"])
                            ],
                            "answer": b["answer"],
                        }
                        for b in blanks
                    ],
                    "explanationZh": "\n".join(
                        f"【{b['label']}】{b['explanation']}" for b in blanks if b.get("explanation")
                    ),
                })
                continue
            m = BLANK_MARKER_RE.search(q["stem"])
            if m:
                before, after = q["stem"][:m.start()], q["stem"][m.end():]
                # 空位token的文字不能真写"____"——mcq-quiz.js的.mcq-blank样式
                # 已经靠border-bottom画了一条蓝色下划线，"____"这四个下划线
                # 字符本身又会在字形基线附近画出另一条黑色细线，两条线叠在
                # 一起变成真实反馈里的"下划线有两道"。改用几个不可见的
                # 全角空格占位——.mcq-blank的min-width:3em本来就保证了这个
                # 空位的视觉宽度，不需要靠文字内容本身撑开。
                before_tokens = tokenize_ja(before)
                stem_tokens = before_tokens + [{"text": "　　　　", "blank": True}] + tokenize_ja(after)
                # kind:"complete"（无选项自由填空）在空位后面紧跟一个纯文本
                # token插入中文提示"（……）"——真实反馈"填空后面加个括号，
                # 显示中文提示"，直接复用已有的token渲染管线（这个token没有
                # kana/blank标记，跟句子里本来就混杂的标点token一样按纯文本
                # 渲染），不需要mcq-quiz.js/page-renderer.js专门为提示开
                # 新的HTML结构。
                if kind == "complete" and q.get("referenceZh"):
                    stem_tokens.insert(len(before_tokens) + 1, {"text": "（" + q["referenceZh"] + "）"})
            else:
                stem_tokens = tokenize_ja(q["stem"])
            item = {
                "id": mcq_id, "category": unit["label"],
                "stemTokens": stem_tokens, "explanationZh": q.get("explanation", ""),
            }
            if kind == "complete":
                item["kind"] = "complete"
                item["referenceJa"] = q["reference"]
            else:
                item["options"] = [
                    {"idx": i + 1, "tokens": tokenize_ja(opt)}
                    for i, opt in enumerate(q["options"])
                ]
                item["answer"] = q["answer"]
            items.append(item)
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("content_path")
    ap.add_argument("--title", required=True)
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--tab-label", default="内容", help="知识点tab的名字，"
                     "比如「语法点」/「单词」")
    ap.add_argument("--password")
    ap.add_argument("--password-hash")
    ap.add_argument("--vocab-quiz", action="store_true", help="额外生成"
                     "「单词测试」tab（跟教材课l17/l18同一套引擎）——"
                     "只给N2词汇页用，语法页的语法点不是要背读音的词，"
                     "不适用这套题型，jp-n2-vocab-page skill才会传这个开关。")
    args = ap.parse_args()
    if not args.password and not args.password_hash:
        ap.error("must provide --password or --password-hash")

    units, mcq_units = load_content(args.content_path)

    os.makedirs(args.out_dir, exist_ok=True)
    audio_dir = os.path.join(args.out_dir, "audio")
    os.makedirs(audio_dir, exist_ok=True)

    from faster_whisper import WhisperModel
    model = WhisperModel("medium", device="cpu", compute_type="int8")
    tmp_wav = os.path.join(tempfile.gettempdir(), "n2_reference_tmp.wav")

    stats = {"ok": 0, "fallback": 0, "failed": 0}
    sentences, questions = build_point_sentences(
        units, model, audio_dir, tmp_wav, stats, args.tab_label
    )
    if os.path.exists(tmp_wav):
        os.remove(tmp_wav)
    print(f"TTS+对齐：{len(sentences)} 句（aligned {stats['ok']}, "
          f"fallback {stats['fallback']}, failed {stats['failed']}）")

    mcq_data = build_mcq_items(mcq_units)
    print(f"练习题：{len(mcq_data)} 道")

    vocab_quiz_data = build_vocab_quiz_items(units) if args.vocab_quiz else None
    if vocab_quiz_data is not None:
        print(f"单词测试：{len(vocab_quiz_data)} 词")

    lesson_data = build_lesson_data(
        args.title, args.subtitle, "", sentences, questions, "audio/",
        quiz_data=vocab_quiz_data
    )
    if mcq_data:
        lesson_data["mcq"] = mcq_data
    # titleDictate：question-block 标题本身就是"要记住的语法点/单词"，允许
    # 默写/填空模式下对标题也出练习（隐藏原文、给输入框、判对错）——跟普通
    # 课文/听力页共用同一份 page-renderer.js/listening-page.js，但那些页面
    # 的标题是场景名/生词表分组名，不该被这套逻辑影响，靠这个显式标记
    # （而不是"标题内容像不像一个词"之类的猜测）区分。
    lesson_data["titleDictate"] = True

    pwd_hash = args.password_hash or hashlib.sha256(args.password.encode("utf-8")).hexdigest()

    out_data_js = os.path.join(args.out_dir, "data.js")
    with open(out_data_js, "w", encoding="utf-8") as f:
        f.write("window.LESSON_DATA = ")
        json.dump(normalize_numbers(lesson_data), f, ensure_ascii=False, indent=2)
        f.write(";\n")

    page = SHELL_TEMPLATE.format(
        title=html.escape(args.title), subtitle=args.subtitle,
        toc_label_html="", side_nav_label="",
        pwd_hash=pwd_hash,
        ICON_PAUSE='<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>',
        ICON_GEAR='<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M19.14,12.94c0.04-0.3,0.06-0.61,0.06-0.94c0-0.32-0.02-0.64-0.07-0.94l2.03-1.58c0.18-0.14,0.23-0.41,0.12-0.61l-1.92-3.32c-0.12-0.22-0.37-0.29-0.59-0.22l-2.39,0.96c-0.5-0.38-1.03-0.7-1.62-0.94L14.4,2.81c-0.04-0.24-0.24-0.41-0.48-0.41h-3.84c-0.24,0-0.43,0.17-0.47,0.41L9.25,5.35C8.66,5.59,8.12,5.92,7.63,6.29L5.24,5.33c-0.22-0.08-0.47,0-0.59,0.22L2.74,8.87C2.62,9.08,2.66,9.34,2.86,9.48l2.03,1.58C4.84,11.36,4.8,11.69,4.8,12s0.02,0.64,0.07,0.94l-2.03,1.58c-0.18,0.14,-0.23,0.41,-0.12,0.61l1.92,3.32c0.12,0.22,0.37,0.29,0.59,0.22l2.39-0.96c0.5,0.38,1.03,0.7,1.62,0.94l0.36,2.54c0.05,0.24,0.24,0.41,0.48,0.41h3.84c0.24,0,0.44-0.17,0.47-0.41l0.36-2.54c0.59-0.24,1.13-0.56,1.62-0.94l2.39,0.96c0.22,0.08,0.47,0,0.59-0.22l1.92-3.32c0.12-0.22,0.07-0.47-0.12-0.61L19.14,12.94z M12,15.6c-1.98,0-3.6-1.62-3.6-3.6s1.62-3.6,3.6-3.6s3.6,1.62,3.6,3.6S13.98,15.6,12,15.6z"/></svg>',
        ICON_LOOP='<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4z"/></svg>',
        ICON_CLOSE='<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>',
        ICON_PREV='<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z"/></svg>',
        ICON_NEXT='<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>',
        ICON_FIRST='<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z"/></svg>',
        ICON_LAST='<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg>',
    )
    out_html = os.path.join(args.out_dir, "index.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"wrote {out_html}, {out_data_js}")


if __name__ == "__main__":
    main()
