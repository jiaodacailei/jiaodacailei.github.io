# -*- coding: utf-8 -*-
"""
用法：
  python build_exam_vocab.py <exam data.js路径>

N2真题模考页（n2-exam-*）用：从問題1〜9（漢字読み/表記/語形成/文脈規定/
言い換え類義/用法/文法1/文法2/文法3）里按题抽出目标词/语法点，写进
data.js顶层的`vocabItems`字段，供页面「生词」tab渲染——外观/交互完全
仿照 l10~l18 教材课的生词tab（同一套 .seg-card 结构，靠
page-renderer.js 新增的 window.PageRenderer.renderCard() 渲染，不是
另起一套自定义卡片样式）。

読解部分（問題10〜14）不抽：没有明确标注"这题考的是哪个词"，抽取要靠
主观判断挑生词，没有官方解析背书，参见 n2-exam/2020-12/LOG.md 里
"重点词汇语法"那次被撤掉的教训。

**这份脚本不是拿来跑了就能直接用的一次性抽取器**——每套真题都需要
重新核对下面这三类真实数据坑，本文件里写死的 override 字典（ZH_MANUAL/
BLANKS_OVERRIDE/問題8 的 overrides）是2020年12月这一套核对完的结果，
换一套真题必须重新核对一遍，不能照抄id号：

1. 問題8（排序题）陷阱：`options[q['answer']-1]` 只是"占了★这个位置的
   那个片段"，不一定是真正被考的语法点——被考的点要从`explanationZh`
   开头的"<pattern>(表示|后接...表示)"<meaning>"。正确语序：..."这段
   固定格式里单独解析，再回去4个选项里找哪个片段包含这段pattern文字来
   定位kana/audio（可能包含额外前后缀，这时候audio不够精确，宁可留
   null也不要放一段包含额外内容的音频，match显示文字对不上）。

2. 中文释义(zh)靠正则从`explanationZh`里锚定抽取——`anchor +
   (意为|表示) + 引号包裹的释义`，anchor因大题类型而异（問題1是"假名
   读音（汉字形）"，問題2是"汉字形（假名读音）"，其余就是目标词本身）。
   抽取完必须全部review一遍：正确答案有时不在被枚举的干扰项对比列表里
   （比如某题解析只列了4个干扰项的释义、没提正确答案本身，因为"从句子
   本身就能看出意思"），这时候regex会返回None，得手动读原文写。

3. 問題1（漢字読み）的`q['stem']`天然是纯假名句子（这道题本来就是"选
   哪个假名读音对"，没有汉字形）——直接当例句会只出现假名、看不到卡片
   标题的汉字词，真实反馈"红框中是假名，不是汉字哟"。改成把quizSentence
   里的假名读音替换成卡片标题的汉字形（`wordKana`在quizSentence里保证
   只出现一次，`str.replace(..., 1)`不会误伤）。activation形不一致时
   （headword是辞书形，例句里出现的是过去式/て形等，比如id27"打ち明ける"
   vs 例句里的"打ち明けた"）blanks要用例句里实际出现的那个活用形，不是
   词典形——脚本里有一段自动校验"blanks是否真的是quizSentence的子串"，
   凡是没通过的都要一条条去读原句手工核对。

4. 顺带核对了一遍furigana——发现2处（不属于这次抽取新引入，是之前
   build_exam_data.py生成时就有的老问题）：単独出现的汉字被
   tokenize_ja()猜错读音（"鮮"猜成せん，应为あざ；"一"在"一仕事"这个
   词里猜成いち，应为ひと），已经在data.js源头改正，不是靠这份脚本
   规避掉，下一套真题构建完也要做一遍类似的人工抽查。

跑完之后务必打印出全部51条人工过一遍（尤其是問題8和zh抽取失败的那几
条），不要不看输出直接信任脚本结果——上一次「重点词汇语法」被用户
说"做得太烂"就是当时验证不够仔细导致的，这次专门记录下来避免重蹈。

5. 問題1（漢字読み）干扰项试点（跟用户讨论后达成的范围：先只做問題1，
   不铺开到其它題型，效果好再考虑扩大）——4个选项不是"1个正确答案+3个
   随便凑的假词"，`explanationZh`里通常会把每个选项对应的汉字写法+释义
   都列出来（格式`かな（かんじ）意为"释义"`，分号分隔），但**不是每个
   选项都有**：有的选项就是纯粹考读音辨析用的音近假名串，字典里查不到
   对应汉字/词义，`explanationZh`对这类选项只会写"第N项属于干扰项，排除"
   或"其余三项属于干扰项，排除"，不会单独解释——这种的不收录（真实数据：
   2020年12月这套问題1一共5题、4个选项，只有10个选项有单独释义可收录，
   另外10个是这种无字典依据的假词，5道题里甚至有一整题（id4）4个选项
   全部没有单独释义，一个都不收）。`MONDAI1_DISTRACTOR_MANUAL`能查到的
   才收录，查不到打印WARN跳过，不自动生成。

   例句**不是**拿原题`stemBlank`模板机械替换生成的——试过这个办法：把
   id5"飛行機は下降を始めた。"的"下降"换成同题干扰项"架空"/"下校"，
   得到"飛行機は架空を始めた。"这种语法通但语义不通的句子（4个选项只是
   读音相近的干扰项，不是语义近似词，未必能套进同一个句子模板里），
   不能拿这种句子给用户当学习例句用，所以每条例句都是手写的，存在
   `MONDAI1_DISTRACTOR_MANUAL`里。audio留null（没有这些手写例句对应的
   录音，选项本身倒是有单独的读音音频`opt['audio']`，但那是单读这个词、
   跟同组正确答案项"整句朗读"的audio语义不一致，混在一起容易让用户以为
   点了播放会听到跟例句一致的整句朗读，宁可不给音频——vocabItems本来就
   支持`audio: null`，`MONDAI8_OVERRIDE`里已经有3条这么用了，页面渲染
   早就处理过这种情况）。
"""
import sys
import json
import re

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def opt_reading(tokens):
    return ''.join(t.get('kana', t['text']) for t in tokens)


def opt_text(tokens):
    return ''.join(t['text'] for t in tokens)


def extract_meaning(zh, word_text, word_kana, mondai):
    if mondai == 1:
        anchor = re.escape(word_kana) + '（' + re.escape(word_text) + '）'
    elif mondai == 2:
        anchor = re.escape(word_text) + '（' + re.escape(word_kana) + '）'
    else:
        anchor = re.escape(word_text)
    pattern = anchor + r'(?:意为|表示)[“"](.+?)[”"]'
    m = re.search(pattern, zh)
    return m.group(1) if m else None


MONDAI1_CLAUSE_RE = re.compile(
    r'([ぁ-ゖァ-ヺー]+)（([^）]+)）意为[“"]([^”"]+)[”"]'
)


def mondai1_distractor_candidates(explanation_zh):
    """从問題1的explanationZh里抽出"かな（かんじ）意为"释义""这种子句，
    返回{かな读音: (漢字写法, 释义)}。只覆盖有单独释义的选项，见上面
    docstring第5条——没匹配到的选项（纯音近假词，没有字典依据）由调用方
    自己按"这个读音不在返回的dict里"来跳过，这个函数不负责判断"没匹配到
    是因为真的没有还是正则写错了"，人工核对靠main()里的WARN打印。"""
    return {kana: (kanji, meaning) for kana, kanji, meaning in MONDAI1_CLAUSE_RE.findall(explanation_zh)}


# 問題1干扰项的手写例句+中译，见上面docstring第5条为什么不能机械生成。
# key是(question id, 干扰项漢字写法)，2020年12月这套10条覆盖完（5题×
# 2〜3个有释义的干扰项，id4这题4个选项都没有单独释义，不出现在这里）。
MONDAI1_DISTRACTOR_MANUAL = {
    (1, '崩さない'): ('積み木を崩さないように、そっと歩いてください。', '请轻轻走路，不要碰倒积木。'),
    (1, '壊さない'): ('おもちゃを壊さないように大事に扱ってください。', '请小心对待玩具，不要弄坏它。'),
    (1, '潰さない'): ('豆腐を潰さないように、そっと持ってください。', '请轻轻拿着豆腐，不要把它捏碎。'),
    (2, '損壊'): ('地震で多くの建物が損壊した。', '地震导致许多建筑物受损。'),
    (2, '被害'): ('台風による被害が各地で報告されている。', '各地都有报告受到台风造成的损害。'),
    (3, '苦しい'): ('長時間走り続けて、息が苦しい。', '长时间跑步，喘不过气来，很难受。'),
    (3, '寂しい'): ('一人暮らしは寂しいと感じることがある。', '一个人生活有时会感到寂寞。'),
    (3, '激しい'): ('昨夜は激しい雨が降った。', '昨晚下了很大的雨。'),
    (5, '架空'): ('この小説に出てくる町は架空のものだ。', '这部小说里出现的城镇是虚构的。'),
    (5, '下校'): ('子供たちは午後3時に下校する。', '孩子们下午3点放学。'),
}


def extract_sentence_zh(zh, mondai, answer):
    """"生词测试"tab需要例句的中文翻译（sentence_zh，跟build_vocab_quiz_
    data.py生成的教材课quiz数据同一个字段名）——问題1/2/3/4/5/7/9的
    explanationZh固定格式是"【解析】<例句中译>\n<选项对比，永远单独一行>"。
    真实踩过的坑：例句中译本身有时也带换行（会话类问题会把两个说话人
    的台词分两行译，比如id34"上司：...\n部下：..."）——如果只取"第一个
    \n前的内容"，会把部下那句漏掉，日语原句(sentence字段)其实是两行都算
    在内的完整对话，中译却只有一半，明显对不上。改成找最后一个\n（选项
    对比那行的前一个换行），从"【解析】"之后到这个位置之间的内容整段
    都算作中译，不管中间有几个换行；単行的普通句子只有一个\n，这个方案
    照样取到同样的结果，不影响原来能正确处理的情形。
    問題6是"...，第N项应用正确，句意：<例句中译>。第1项应用错误..."，
    N是这道题的正确答案序号（answer），不是固定第几项。
    問題8没有走这个函数——5道题的中译是从原文手工抄的，直接写在
    MONDAI8_OVERRIDE里（问题8的explanationZh只有一句"句意：..."，对应
    的是排好序的整句话，不是某个片段，抽取逻辑跟其它类型不是一回事，
    没必要为了5条硬凑一个正则）。"""
    if mondai == 6:
        m = re.search(r'第' + str(answer) + r'项应用正确，句意：(.+?)。', zh)
        return m.group(1) + '。' if m else None
    m = re.match(r'^.解析.', zh)
    if not m:
        return None
    last_nl = zh.rfind('\n')
    if last_nl == -1 or last_nl <= m.end():
        return None
    return zh[m.end():last_nl]


# ↓↓↓ 换一套真题时，先跑一遍不带override的版本看哪些id落进"需要人工
# 核对"的桶里（問題8全部5题 + zh抽取失败 + blanks不在quizSentence里），
# 再针对那些id填这三个字典。下面是2020年12月这套的结果，仅供参照格式。
MONDAI8_OVERRIDE = {
    43: {'text': 'とおりに', 'kana': 'とおりに', 'audio': 'audio/q43_opt3.mp3',
         'zh': '和……一样，按照……',
         'sentence_zh': '昨天第一次试着做了面包。是按照料理杂志上写的配方做的，（面包）却没有很好地发起来。'},
    44: {'text': 'に対して', 'kana': 'にたいして', 'audio': None,
         'zh': '相对于……；比例是……',
         'sentence_zh': '所谓“10倍粥”就是米和水以1:10的比例做出来的粥。'},
    45: {'text': '決して', 'kana': 'けっして', 'audio': 'audio/q45_opt1.mp3',
         'zh': '绝对不，断然不',
         'sentence_zh': '我工作的贸易公司，与大公司比起来，肯定没有大公司规模那样大，但是只要有干劲儿，即使是新人也可以被委以重任，是一份很有意义的工作。'},
    46: {'text': '抜きに', 'kana': 'ぬきに', 'audio': None,
         'zh': '除去，拿掉',
         'sentence_zh': '她是20世纪70年代的一位非常活跃的爵士乐钢琴家。她的存在非常重要，以至于不谈她的话就没有办法去谈日本的爵士乐。'},
    47: {'text': '思い込み', 'kana': 'おもいこみ', 'audio': None,
         'zh': '臆想，自认为',
         'sentence_zh': '送别人东西的时候，如果只按照自己的喜好去选的话，不仅不会取悦对方，还有可能会给别人添麻烦。想一下对方的兴趣和情况再做决定吧。'},
}
ZH_MANUAL = {
    21: '引导，向导',
    25: '触摸，抚摸',
    41: '「来る」的尊敬语说法',
    # 正则本身抽取成功（"如果田中你可以/愿意的话"），但原句里的人名"田中"
    # 混进了释义里——手工去掉人名，改成通用表达。
    42: '如果……可以/愿意的话',
}
BLANKS_OVERRIDE = {
    27: '打ち明けた',
}
# 例句中译(sentence_zh，"生词测试"tab要用)——先跑一遍空字典看extract_
# sentence_zh()哪些id提取失败，再把失败的手工读原文填进来。問題9这4条
# 失败是必然的：quizSentence来自共享文章里的某一句原文（build_exam_
# vocab.py主流程里从passageSentences按子串定位到的那句），explanationZh
# 对問題9压根没有"【解析】<例句中译>\n"这个开头格式（直接进选项对比），
# 也没有任何地方存过这句共享文章原文对应的中译——4句译文是根据文章
# 原文自己翻的，不是从exam数据的其它字段抄来的。
SENTENCE_ZH_MANUAL = {
    48: '最近，这是护理现场备受关注的东西，请问大家知道吗？',
    49: '于是，作为“动物治疗法”的替代方案，最近“机器人治疗法”开始受到关注。',
    50: '据说通过与这类机器人的接触，能够获得精神安定、沟通能力改善等效果。',
    51: '然后，我想变得能够为医疗领域做出贡献。',
}
MONDAI_LABEL = {
    1: '問題1 漢字読み', 2: '問題2 表記', 3: '問題3 語形成', 4: '問題4 文脈規定',
    5: '問題5 言い換え類義', 6: '問題6 用法', 7: '問題7 文法1',
    8: '問題8 文法2', 9: '問題9 文法3',
}


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    raw = open(path, encoding='utf-8').read()
    prefix = raw[:raw.index('{')]
    body = raw[raw.index('{'):]
    body = re.sub(r';\s*$', '', body.strip())
    d = json.loads(body)

    items = []
    for m in d['mondaiList']:
        if m['mondai'] > 9:
            continue
        if m['mondai'] == 8:
            for b in m['blocks']:
                for q in b['questions']:
                    ov = MONDAI8_OVERRIDE.get(q['id'])
                    if not ov:
                        print('WARN: 問題8 id' + str(q['id']) + ' 没有override，需要人工核对')
                        continue
                    items.append({
                        'mondai': 8, 'qid': q['id'],
                        'wordText': ov['text'], 'wordKana': ov['kana'],
                        'audio': ov['audio'],
                        'quizSentence': ''.join(t['text'] for t in q['stem']['tokens']),
                        'zh': ov['zh'],
                        'sentence_zh': ov['sentence_zh'],
                    })
            continue
        if m['mondai'] == 9:
            for b in m['blocks']:
                passage_sents = b['passageSentences']
                for q in b['questions']:
                    opt = q['options'][q['answer'] - 1]
                    word_text = opt_text(opt['tokens'])
                    word_kana = opt_reading(opt['tokens'])
                    example = None
                    for s in passage_sents:
                        stext = ''.join(t['text'] for t in s['tokens'])
                        if word_text in stext:
                            example = stext
                            break
                    items.append({
                        'mondai': 9, 'qid': q['id'],
                        'wordText': word_text, 'wordKana': word_kana,
                        'audio': opt.get('audio'),
                        'quizSentence': example,
                        'zh_source': q['explanationZh'],
                    })
            continue
        for b in m['blocks']:
            for q in b['questions']:
                if m['mondai'] == 6:
                    opt = q['options'][q['answer'] - 1]
                    sent = opt['sentences'][0]
                    items.append({
                        'mondai': 6, 'qid': q['id'],
                        'wordText': opt_text(q['stemWord']['tokens']),
                        'wordKana': opt_reading(q['stemWord']['tokens']),
                        'audio': q['stemWord']['audio'],
                        'quizSentence': ''.join(t['text'] for t in sent['tokens']),
                        'zh_source': q['explanationZh'],
                        'answer': q['answer'],
                    })
                    continue
                opt = q['options'][q['answer'] - 1]
                opt_toks = opt['tokens']
                if m['mondai'] == 1:
                    blank_tok = next(t for t in q['stemBlank']['tokens'] if t.get('blank'))
                    word_text = blank_tok['text']
                    word_kana = opt_reading(opt_toks)
                else:
                    word_text = opt_text(opt_toks)
                    word_kana = opt_reading(opt_toks)
                items.append({
                    'mondai': m['mondai'], 'qid': q['id'],
                    'wordText': word_text, 'wordKana': word_kana,
                    'audio': q['stem']['audio'],
                    'quizSentence': ''.join(t['text'] for t in q['stem']['tokens']),
                    'zh_source': q['explanationZh'],
                })
                if m['mondai'] == 1:
                    candidates = mondai1_distractor_candidates(q['explanationZh'])
                    for dopt in q['options']:
                        if dopt['idx'] == q['answer']:
                            continue
                        dkana = opt_reading(dopt['tokens'])
                        cand = candidates.get(dkana)
                        if not cand:
                            continue
                        dkanji, dmeaning = cand
                        manual = MONDAI1_DISTRACTOR_MANUAL.get((q['id'], dkanji))
                        if not manual:
                            print('WARN: 問題1 id' + str(q['id']) + ' 干扰项"' + dkanji
                                  + '"缺手写例句，需要人工补 MONDAI1_DISTRACTOR_MANUAL')
                            continue
                        dsentence, dsentence_zh = manual
                        items.append({
                            'mondai': 1, 'qid': 1000 + q['id'] * 10 + dopt['idx'],
                            'wordText': dkanji, 'wordKana': dkana,
                            'audio': None,
                            'quizSentence': dsentence,
                            'zh': dmeaning,
                            'sentence_zh': dsentence_zh,
                        })

    for it in items:
        if 'sentence_zh' in it:
            continue
        it['sentence_zh'] = SENTENCE_ZH_MANUAL.get(
            it['qid'],
            extract_sentence_zh(it['zh_source'], it['mondai'], it.get('answer')),
        )
        if 'zh' not in it:
            if it['qid'] in ZH_MANUAL:
                it['zh'] = ZH_MANUAL[it['qid']]
            else:
                it['zh'] = extract_meaning(it['zh_source'], it['wordText'], it['wordKana'], it['mondai'])
        it.pop('zh_source', None)
        it.pop('answer', None)

    items.sort(key=lambda x: x['qid'])

    # 問題1（漢字読み）的q['stem']是"填好正确假名读音"的句子——因为这道题
    # 本来就是"选哪个假名读音对"，stem对这类题天然就是纯假名形式，没有
    # 汉字。直接拿来当"生词"tab的例句会只出现假名、看不到卡片标题里那个
    # 汉字词（比如标题"倒さない"，例句却是"たおさないように…"）——真实
    # 反馈"红框中是假名，不是汉字哟"。改成把quizSentence里的假名读音替换
    # 成卡片标题的汉字形，跟标题保持一致，例句读起来也符合正常日语书写
    # 习惯。wordKana在quizSentence里保证只出现一次（构造时已验证过），
    # replace(..., 1)不会误伤其它地方。
    for it in items:
        if it['mondai'] == 1 and it['wordKana'] != it['wordText']:
            it['quizSentence'] = it['quizSentence'].replace(it['wordKana'], it['wordText'], 1)

    for it in items:
        it['blanks'] = BLANKS_OVERRIDE.get(it['qid'], it['wordText'])

    bad_blanks = [it for it in items if it['blanks'] not in (it['quizSentence'] or '')]
    zh_fails = [it for it in items if not it['zh']]
    missing_quiz = [it for it in items if not it['quizSentence']]
    sentence_zh_fails = [it for it in items if not it['sentence_zh']]
    print('total', len(items))
    print('blanks not matching quizSentence:', [it['qid'] for it in bad_blanks])
    print('zh extraction failed:', [it['qid'] for it in zh_fails])
    print('missing quizSentence:', [it['qid'] for it in missing_quiz])
    print('sentence_zh extraction failed:', [it['qid'] for it in sentence_zh_fails])
    if bad_blanks or zh_fails or missing_quiz or sentence_zh_fails:
        print('以上id需要人工核对/补override，脚本不会自动写入data.js，先处理完再重跑')
        sys.exit(1)

    vocab_items = []
    quiz_items = []
    for it in items:
        tokens = ([{'text': it['wordText'], 'kana': it['wordKana']}]
                   if it['wordKana'] != it['wordText']
                   else [{'text': it['wordText']}])
        vocab_items.append({
            'id': it['qid'],
            'mondai': it['mondai'],
            'mondaiLabel': MONDAI_LABEL[it['mondai']],
            'tokens': tokens,
            'zh': it['zh'],
            'notes': '',
            'blanks': [it['blanks']],
            'audio': it['audio'],
            'quizSentence': it['quizSentence'],
        })
        # 跟 build_vocab_quiz_data.py 生成的教材课quiz数据同一套字段名，
        # listening-page.js的単語テスト引擎（"填空题/听音频写假名/中文
        # 写假名/日文写中文"四种题型）不用改一行就能直接吃这份数据——
        # category统一填"other"（这些词不是来自"会话/课文"，是从問題
        # 1〜9里抽出来的，跟教材课"会话相关/课文相关/其他"三分类的语义
        # 对不上，全归"other"最贴切，単語テスト页面上会显示成"其他单词"
        # 这一个分类，不会出现空的"会话相关"分类可选）。
        quiz_items.append({
            'id': it['qid'],
            'text': it['wordText'],
            'kana': it['wordKana'],
            'zh': it['zh'],
            'sentence': it['quizSentence'],
            'sentence_zh': it['sentence_zh'],
            'blank': it['blanks'],
            'category': 'other',
        })

    d['vocabItems'] = vocab_items
    d['vocabQuiz'] = quiz_items
    out = prefix + json.dumps(d, ensure_ascii=False, indent=2) + ';\n'
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(out)
    print('written', len(vocab_items), 'vocabItems +', len(quiz_items), 'vocabQuiz entries to', path)


if __name__ == '__main__':
    main()
