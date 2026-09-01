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

3. blanks（填空定位用的文字）不一定等于卡片标题显示的词典形/汉字形：
   問題1是読み题，quizSentence用的是假名读音而不是汉字，blanks要用
   假名读音；活用形不一致时（headword是辞书形，例句里出现的是过去式/
   て形等）blanks要用例句里实际出现的那个活用形，不是词典形——脚本里
   有一段自动校验"blanks是否真的是quizSentence的子串"，凡是没通过的
   都要一条条去读原句手工核对。

4. 顺带核对了一遍furigana——发现2处（不属于这次抽取新引入，是之前
   build_exam_data.py生成时就有的老问题）：単独出现的汉字被
   tokenize_ja()猜错读音（"鮮"猜成せん，应为あざ；"一"在"一仕事"这个
   词里猜成いち，应为ひと），已经在data.js源头改正，不是靠这份脚本
   规避掉，下一套真题构建完也要做一遍类似的人工抽查。

跑完之后务必打印出全部51条人工过一遍（尤其是問題8和zh抽取失败的那几
条），不要不看输出直接信任脚本结果——上一次「重点词汇语法」被用户
说"做得太烂"就是当时验证不够仔细导致的，这次专门记录下来避免重蹈。
"""
import sys
import json
import re


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


# ↓↓↓ 换一套真题时，先跑一遍不带override的版本看哪些id落进"需要人工
# 核对"的桶里（問題8全部5题 + zh抽取失败 + blanks不在quizSentence里），
# 再针对那些id填这三个字典。下面是2020年12月这套的结果，仅供参照格式。
MONDAI8_OVERRIDE = {
    43: {'text': 'とおりに', 'kana': 'とおりに', 'audio': 'audio/q43_opt3.mp3',
         'zh': '和……一样，按照……'},
    44: {'text': 'に対して', 'kana': 'にたいして', 'audio': None,
         'zh': '相对于……；比例是……'},
    45: {'text': '決して', 'kana': 'けっして', 'audio': 'audio/q45_opt1.mp3',
         'zh': '绝对不，断然不'},
    46: {'text': '抜きに', 'kana': 'ぬきに', 'audio': None,
         'zh': '除去，拿掉'},
    47: {'text': '思い込み', 'kana': 'おもいこみ', 'audio': None,
         'zh': '臆想，自认为'},
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

    for it in items:
        if 'zh' in it:
            continue
        if it['qid'] in ZH_MANUAL:
            it['zh'] = ZH_MANUAL[it['qid']]
        else:
            it['zh'] = extract_meaning(it['zh_source'], it['wordText'], it['wordKana'], it['mondai'])
        it.pop('zh_source', None)

    items.sort(key=lambda x: x['qid'])

    for it in items:
        if it['qid'] in BLANKS_OVERRIDE:
            it['blanks'] = BLANKS_OVERRIDE[it['qid']]
        elif it['mondai'] == 1:
            it['blanks'] = it['wordKana']
        else:
            it['blanks'] = it['wordText']

    bad_blanks = [it for it in items if it['blanks'] not in (it['quizSentence'] or '')]
    zh_fails = [it for it in items if not it['zh']]
    missing_quiz = [it for it in items if not it['quizSentence']]
    print('total', len(items))
    print('blanks not matching quizSentence:', [it['qid'] for it in bad_blanks])
    print('zh extraction failed:', [it['qid'] for it in zh_fails])
    print('missing quizSentence:', [it['qid'] for it in missing_quiz])
    if bad_blanks or zh_fails or missing_quiz:
        print('以上id需要人工核对/补override，脚本不会自动写入data.js，先处理完再重跑')
        sys.exit(1)

    vocab_items = []
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

    d['vocabItems'] = vocab_items
    out = prefix + json.dumps(d, ensure_ascii=False, indent=2) + ';\n'
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(out)
    print('written', len(vocab_items), 'vocabItems to', path)


if __name__ == '__main__':
    main()
