# -*- coding: utf-8 -*-
"""
用法：
  python build_page.py <原始音频> <enriched.json> <输出目录> \
      --title "标题" --subtitle "副标题" --password sairai

<enriched.json> 是 merge_groups.py 的输出：{"sentences": [...], "questions": [...]}
（简单流程/无分组内容也可以用，questions 传空数组即可，此时不生成 h3/概览/答案，
 只有 h2=mondai 或完全没有分组，直接把所有 sentences 按 h2 分组渲染）。

<输出目录> 会生成：
  index.html        密码门 + noindex + 博客同款目录侧栏 + 三层播放控制的听力页
  audio/seg-NN.mp3   每句切出来的音频片段

生成后把 <输出目录> 放到 docs/private/<slug>/ 下即可通过个人网站访问，
但不要把它加进 blog/index.html、posts.json 或站内导航——保持"不公开链接"。

页面依赖三个共用文件（不再是每个页面各自内联一份，改样式/改交互只用改这些文件
一次，不用重新生成每个页面）：docs/css/listening-page.css、docs/js/listening-page.js
（听力页专属：播放器/tab/跟读高亮），docs/js/private-gate.js（密码门逻辑，不只是
听力页在用，其它私有页面比如枢纽页也用这份——解锁状态按密码哈希存 sessionStorage，
不按页面路径存，同一个密码在多个页面通用时解锁一处、其它页面自动跳过登录）。
**本地验证不能再直接双击 index.html 用 file:// 打开**——浏览器对 file:// 页面加载
本地其它文件有安全限制，绝对路径 `/css/...`、`/js/...` 解析不到。改用
`python -m http.server` 在 docs/ 目录起个本地服务器，用 http://localhost:8000/
private/<slug>/ 访问。
"""
import os
import json
import html
import hashlib
import argparse
import subprocess
import imageio_ffmpeg
import pykakasi

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
_kks = pykakasi.kakasi()


def _is_kanji(ch):
    return '一' <= ch <= '鿿'


# pykakasi 是按单字/常见复合词猜读音的，罕见组合容易读错，已经踩过两类坑：
# 1) 单字在孤立语境下的默认读音，放进特定复合词里其实要变——"表"单独最常见的
#    读音是おもて（"正面"），但在"スケジュール表"（日程表）这个复合词里应该读
#    ひょう；这类只在"上一个 token 是特定词"时才生效，不能无条件覆盖每一个
#    "表"字（其它页面/其它上下文里独立出现的"表"多半确实该读おもて）。
# 2) 纯粹的库内部转换 bug，不管上下文都会错——"入っ"（"入る"促音变前的词干，
#    后面接 て/たり/た）pykakasi 会输出无效假名"いっっ"（多出一个っ），这个
#    token 只可能来自五段动词"入る"，不存在"入っ"读别的音的情况，可以无条件覆盖。
# 两种覆盖都只改 `hira`（显示的读音文本），不改 `orig`，字符长度对
# char_times 下标的计算完全没有影响，不会连带影响跟读高亮的时间戳对齐。
_TOKEN_READING_OVERRIDES_BY_PREV = {
    ("スケジュール", "表"): "ひょう",
    # "その日"（那天，独立指某一天）该读ひ，pykakasi 默认给孤立的"日"字读にち
    # （日期计数用法，比如"1日"=いちにち这种搭配才对）。
    ("その", "日"): "ひ",
    # "20日"是日期特殊读法はつか（不是にじゅうにち），只在"20"后面才触发，不影响
    # "1日"(いちにち)/"3日"(みっか，还没遇到但同理不受影响)这些其它数字+日的组合。
    ("20", "日"): "はつか",
    # "か月"（〜个月，时长量词，比如"1か月"=いっかげつ）该读げつ，pykakasi 默认
    # 给孤立的"月"字读がつ（日历月份读音，比如"1月"=いちがつ才对，这个场景数字
    # 后面直接跟"月"、中间没有"か"）。
    ("か", "月"): "げつ",
}
_TOKEN_READING_OVERRIDES_UNCONDITIONAL = {
    "入っ": "はいっ",
    # 人名"千尋"（比如《千と千尋の神隠し》的女主角）该读ちひろ，pykakasi 按
    # 通用音读猜成せんじん——这类专有名词的正确读音本来就不是"看上下文规律"
    # 能推出来的，得靠具体知识判断，是这个覆盖表里少数几个"必须无条件覆盖"
    # 的场景之一（"千尋"作为人名比作为普通词的用法常见得多，不太会有需要
    # 保留せんじん这个读音的场景）。
    "千尋": "ちひろ",
}


def _resolve_hira(orig, hira, prev_orig, next_char=None):
    """`_TOKEN_READING_OVERRIDES_*` 处理"固定搭配"（触发条件是具体的某个
    prev_orig 字面值），但"人"这个字的正确读音规律更通用，值得单独写一条规则
    而不是不断往字典里加案例——孤立成词的"人"（不是"外国人""成人""大人""人気"
    这类已经被 pykakasi 自己合并成一个多字 token 的复合词，那些不受这条规则
    影响）几乎总是该读ひと（"〜的人"，独立名词），只有紧跟在数字后面表示
    "多少人"这个数量词读法时才该读にん/じん（"3人"=さんにん、"20人"=にじゅう
    にん）。真实案例：一开始只加了 `("の","人")→"ひと"` 这一条件，只能覆盖
    "の"独立成词紧跟在"人"前面的情况（比如"同世代の人"），但"人"前面的词大量
    时候是跟"の"合并成一个 token 的（比如"他の"整个是一个 token，"の"不会单独
    出现），或者是动词/形容词连体形（"いる人""する人""忙しい人"），这些都会被
    这条窄规则漏掉——直接按"prev_orig 是不是数字"这个更通用的条件判断，一次
    覆盖所有这些场景，不用每发现一种新的前置词形态就加一条。
    """
    # 判断"前一个 token 是不是数字"不能用 prev_orig.isdigit() 整串判断——
    # pykakasi 会把"第"跟紧跟着的阿拉伯数字合并成一个 token（"第２"作为一个
    # token，不是"第"+"２"两个），整串 isdigit() 会因为含有"第"字而判 False，
    # 漏掉"第２位"这种真实场景，必须看 prev_orig 的最后一个字符是不是数字。
    prev_ends_with_digit = bool(prev_orig) and prev_orig[-1].isdigit()
    if orig == "人" and not prev_ends_with_digit:
        return "ひと"
    # "位"孤立成词时 pykakasi 默认给くらい（"大概/左右"，比如"3人くらい"里的
    # くらい，但那种くらい本来就是假名写的，不会走到这条判断），但紧跟在阿拉伯
    # 数字后面表示名次（"第２位"=だいにい、"20位"=にじゅうい）时该读い——跟
    # "人"是同一种坑：汉字数字会被 pykakasi 直接合并成一个 token（"一位"=
    # いちい、"第一位"=だいいちい，不受这条规则影响），只有阿拉伯数字+"位"
    # 会被拆成独立 token 然后读错。
    if orig == "位" and prev_ends_with_digit:
        return "い"
    # "その後"是个歧义词，两个读音都是常见的正确用法，不能像"その日"那样无条件
    # 覆盖：そのご（书面语，"之后/其后"，常作句首连接副词用，后面接逗号停顿——
    # 比如课文里"その後，デジタル技術の開発が進むとともに…"）vs そのあと（口语，
    # "那之后"，直接接续下一个动作、中间没有停顿——比如"その後食事に行った"）。
    # pykakasi 默认给孤立的"後"字读のち（另一个真实存在但这里都用不上的读音），
    # 两种都不对。用"紧跟着的下一个字符是不是逗号"这个信号区分：书面语用法
    # 后面几乎总有停顿标点，口语接续用法后面直接是下一个词，没有标点。
    if orig == "後" and prev_orig == "その" and next_char in ("，", "、"):
        return "ご"
    return hira


def _split_trailing_kana(orig, hira):
    """把"汉字+送假名"合并成一个 token 时（比如形容词过去式"悪かった"，pykakasi
    切成"悪か"/"った"两个 token，前一个 token 原文="悪か"读音="わるか"），假名
    注音不应该连送假名一起标——正确的排版规范是只给汉字本身标注读音（"悪"→
    "わる"），后面已经是假名的"か"直接照抄显示，不用再在 <rt> 里重复一遍。
    做法：只要 orig 结尾字符不是汉字、且这个字符跟 hira 结尾字符完全一致（说明
    这确实是原样保留的送假名，不是汉字注音的一部分），就把这个字符从两边一起
    摘掉，挪到返回的 suffix 里，重复到摘不动为止（比如"忙しかった"里的
    "忙しか"要连续摘两次"か""し"才能摘到纯汉字"忙"）。摘的过程中永远留至少
    一个字符在 core 里，不会摘穿。"""
    core_orig, core_hira, suffix = orig, hira, ""
    while (len(core_orig) > 1 and core_hira and not _is_kanji(core_orig[-1])
           and core_orig[-1] == core_hira[-1]):
        suffix = core_orig[-1] + suffix
        core_orig = core_orig[:-1]
        core_hira = core_hira[:-1]
    return core_orig, core_hira, suffix


def ruby_html(text, char_times=None):
    """假名注音渲染。有 char_times（refine_boundaries.py 用词级时间戳文本对齐算出来
    的、这句里每个字符对应的绝对播放时间）时，额外给每个分词包一层
    `<span class="tw" data-t="...">`，播放时前端按 audio.currentTime 找到当前应该
    高亮的词。没有 char_times（简单流程没跑 refine_boundaries.py，或者这句对齐质量
    太差被跳过）就退化成纯 <ruby> 输出，不带高亮能力——静态展示效果不受影响，
    只是没有跟读高亮。
    """
    lines = text.split("\n")
    out_lines = []
    char_idx = 0
    for li, line in enumerate(lines):
        tokens = _kks.convert(line)
        parts = []
        prev_orig = None
        line_offset = 0
        for t in tokens:
            orig = t['orig']
            hira = t['hira']
            tok_len = len(orig)
            next_char = line[line_offset + tok_len] if line_offset + tok_len < len(line) else ""
            line_offset += tok_len
            if orig in _TOKEN_READING_OVERRIDES_UNCONDITIONAL:
                hira = _TOKEN_READING_OVERRIDES_UNCONDITIONAL[orig]
            elif (prev_orig, orig) in _TOKEN_READING_OVERRIDES_BY_PREV:
                hira = _TOKEN_READING_OVERRIDES_BY_PREV[(prev_orig, orig)]
            else:
                hira = _resolve_hira(orig, hira, prev_orig, next_char)
            prev_orig = orig
            t_time = None
            if char_times is not None and char_idx < len(char_times):
                t_time = char_times[char_idx]
            char_idx += tok_len
            if any(_is_kanji(ch) for ch in orig) and hira != orig:
                core_orig, core_hira, suffix = _split_trailing_kana(orig, hira)
                inner = f'<ruby>{core_orig}<rt>{core_hira}</rt></ruby>{suffix}'
            else:
                inner = orig
            # 标点/符号（「、」「。」「?」之类）不算"读到的词"，不参与跟读高亮——
            # pykakasi 分词里纯标点 token 没有假名/汉字，isalnum() 全假，用这个判断跳过。
            has_content = any(ch.isalnum() for ch in orig)
            if t_time is not None and has_content:
                parts.append(f'<span class="tw" data-t="{t_time:.2f}">{inner}</span>')
            else:
                parts.append(inner)
        out_lines.append(''.join(parts))
        if li < len(lines) - 1:
            char_idx += 1  # 换行符本身也占一个字符位，对齐 char_times 的下标
    return '<br>'.join(out_lines)


def _probe_duration(path):
    """已存在文件的实际时长（秒），探测失败（文件损坏/不是有效音频）返回 None。"""
    probe = subprocess.run(
        [FFMPEG, "-i", path], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    lines = [l for l in probe.stderr.splitlines() if "Duration" in l]
    if not lines:
        return None
    hms = lines[0].split("Duration:")[1].split(",")[0].strip()
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def cut_segments(audio_path, sentences, out_audio_dir):
    """跳过重切的判断不能只看"文件存在"——改时间戳（修边界/重新排序）之后重新跑
    这个函数时，已经切过的旧文件会原样保留、不会跟着刷新，页面看起来"文字/翻译
    是新的，音频却还是旧的"（真实踩过的坑：改完 enriched.json 里的边界，忘了这一
    出，实际听到的还是修复前的音频，且这个问题不会在任何 HTML 层面的检查里
    暴露出来，只有实际播放或者比对音频时长才能发现）。现在改成：文件存在时探测
    它的实际时长，跟这句现在期望的时长（end-start）对不上才重切，对得上（在
    容差范围内）才真正跳过。
    """
    os.makedirs(out_audio_dir, exist_ok=True)
    for s in sentences:
        out_file = os.path.join(out_audio_dir, f"seg-{s['id']:03d}.mp3")
        expected_dur = s["end"] - s["start"]
        if os.path.exists(out_file):
            actual_dur = _probe_duration(out_file)
            if actual_dur is not None and abs(actual_dur - expected_dur) < 0.15:
                continue
        subprocess.run(
            [FFMPEG, "-y", "-ss", str(s["start"]), "-t", str(expected_dur), "-i", audio_path,
             "-ar", "44100", "-ac", "1", "-b:a", "96k", out_file],
            capture_output=True
        )


def sentence_card_html(s, audio_rel):
    zh = html.escape(s["zh"]).replace("\n", "<br>")
    notes_html = ""
    if s.get("notes"):
        notes_html = f'<div class="seg-notes">{html.escape(s["notes"])}</div>'
    # char_times 是绝对时间戳（跟 s["start"]/s["end"] 一个坐标系），但这句自己的
    # audio 文件是从它自己的 start 开始单独切出来的（文件内 t=0 对应 s["start"]），
    # 所以喂给 ruby_html 之前要减去 s["start"] 转成这个音频文件内部的相对时间。
    char_times = s.get("char_times")
    rel_char_times = [round(t - s["start"], 2) for t in char_times] if char_times else None
    ja_html = ruby_html(s["text"], rel_char_times) if rel_char_times else s["furigana"]
    # 会话类课文常有说话人（比如"王：""担当者："）——独立成一栏用绝对定位放在
    # .seg-ja 之外的左侧内边距里，不要拼进 text 里再喂给 ruby_html（那样说话人
    # 会被当成日语原文的一部分参与跟读高亮/默写比对/填空挖空，都不合适，见
    # CSS 里 .seg-speaker 的注释）。没有 speaker 字段的句子（绝大多数场景，
    # 包括所有没有说话人的独白/课文）跟以前完全一样，.seg-card 不加
    # has-speaker 类、不多出这个 div，布局完全不受影响。
    speaker_html = ""
    card_class = "seg-card"
    if s.get("speaker"):
        card_class += " has-speaker"
        speaker_kana = s.get("speaker_kana")
        speaker_inner = (
            f'<ruby>{html.escape(s["speaker"])}<rt>{html.escape(speaker_kana)}</rt></ruby>'
            if speaker_kana else html.escape(s["speaker"])
        )
        speaker_html = f'<div class="seg-speaker">{speaker_inner}</div>\n          '
    # 填空练习模式挖哪几个空、正确答案是什么，来自 `blanks`（这句原文里要
    # 挖空的具体文字组成的列表，比如 ["映画にしても音楽にしても"]）——不是从
    # `notes` 里用正则解析出来的：`notes` 给人看的解释经常用抽象占位字母
    # （"AにしてもBにしても"）或者跟正文不完全一致的写法（词典型 vs 活用形），
    # 靠字符串匹配去猜这两种情况根本猜不出来，而且猜错了没有任何报错，只有
    # 打开填空模式实际点开才会发现。`blanks` 由内容作者显式指定，就是这句
    # 原文里的真实子串，前端按这个精确定位，不用再猜。空列表/没有这个字段
    # 都表示这句不出填空题，`notes` 照常只当纯展示的解释文字用。
    blanks_attr = ""
    if s.get("blanks"):
        blanks_json = json.dumps(s["blanks"], ensure_ascii=False)
        blanks_attr = f' data-blanks="{html.escape(blanks_json)}"'
    return f'''
        <div class="{card_class}" id="card-a{s['id']}"{blanks_attr}>
          {speaker_html}<p class="seg-ja">{ja_html}</p>
          <p class="seg-zh">{zh}</p>{notes_html}
          <audio id="a{s['id']}" preload="none" src="{audio_rel}seg-{s['id']:03d}.mp3"></audio>
        </div>'''


def question_block_html(mondai_idx, q_idx, question_label, overview, answer, sentences, audio_rel):
    overview_html = f'<p class="q-overview">{html.escape(overview)}</p>' if overview else ""
    answer_html = ""
    if answer:
        answer_html = f'''
        <details class="seg-answer">
          <summary>答えを見る</summary>
          <div>{html.escape(answer)}</div>
        </details>'''
    cards = "\n".join(sentence_card_html(s, audio_rel) for s in sentences)
    scope_id = f"q-{mondai_idx}-{q_idx}"
    return f'''
      <div class="question-block" id="{scope_id}" data-scope="question">
        <h3>{html.escape(question_label)}</h3>
        {overview_html}{answer_html}
        {cards}
      </div>'''


def mondai_section_html(mondai_idx, mondai_label, question_blocks_html, active):
    scope_id = f"m-{mondai_idx}"
    cls = "mondai-section tab-active" if active else "mondai-section"
    return f'''
    <section class="{cls}" id="{scope_id}" data-scope="mondai">
      <h2>{html.escape(mondai_label)}</h2>
      {question_blocks_html}
    </section>'''


# "单词测试" tab 是运行时纯前端生成的互动题（填空/听音频写假名/中文写假名/日文写
# 中文），不是像其它大题那样预先渲染好一堆 .seg-card——这里只需要一个空容器 + 一份
# 内嵌 JSON 数据（build_vocab_quiz_data.py 生成），listening-page.js 里的 quiz 引擎
# 找到这个 <script> 标签就会接管渲染，找不到（没传 --quiz-json 的普通听力页）就是
# 纯静态无操作，不影响任何现有页面。
# 用跟其它大题一样的 data-scope="mondai" + 一份（空的）side-nav-list/snm-nums-list，
# 是为了让 tab 切换那段共享 JS（按下标并行 toggle 这三类 NodeList）不用改一行就能
# 正确处理"多出来一个 tab"的情况，不用专门为这个 tab 加分支逻辑。
def quiz_section_html(mondai_idx, quiz_json_data, active):
    scope_id = f"m-{mondai_idx}"
    cls = "mondai-section tab-active" if active else "mondai-section"
    quiz_json = json.dumps(quiz_json_data, ensure_ascii=False)
    return f'''
    <section class="{cls}" id="{scope_id}" data-scope="mondai">
      <h2>単語テスト</h2>
      <div class="quiz-app" id="quizApp">
        <div class="quiz-toolbar">
          <div class="quiz-progress" id="quizProgress">0 / 0</div>
          <button type="button" class="quiz-reset-btn" id="quizResetErrors">清除使用记录</button>
        </div>
        <div class="quiz-card" id="quizCard">
          <div class="quiz-type-label" id="quizTypeLabel"></div>
          <div class="quiz-prompt" id="quizPrompt"></div>
          <button type="button" class="quiz-play-btn" id="quizPlayBtn" style="display:none">▶ 播放发音</button>
          <div class="quiz-input-row">
            <input type="text" class="quiz-input" id="quizInput" autocomplete="off" placeholder="在此输入…">
            <button type="button" class="quiz-btn quiz-check" id="quizCheck">確認</button>
            <button type="button" class="quiz-btn quiz-next" id="quizNext" style="display:none">次へ</button>
          </div>
          <div class="quiz-status" id="quizStatus"></div>
        </div>
        <div class="quiz-done" id="quizDone" style="display:none">🎉 本轮全部完成！</div>
      </div>
      <script type="application/json" id="vocab-quiz-data">{quiz_json}</script>
    </section>'''


def side_nav_list_html(mondai_idx, question_labels, active):
    """桌面 .toc 侧栏 / 手机 .toc-float-panel 都用这份列表（结构与 toc.js 生成的一致）。"""
    cls = "side-nav-list tab-active" if active else "side-nav-list"
    items = "\n".join(
        f'<li class="toc-h2"><a class="side-nav-btn" data-target="q-{mondai_idx}-{qi}">{html.escape(label)}</a></li>'
        for qi, label in enumerate(question_labels, 1)
    )
    return f'<ul class="{cls}" data-mondai-idx="{mondai_idx}">{items}</ul>'


def mobile_nums_list_html(mondai_idx, question_labels, active):
    """手机悬浮目录收起状态下的数字按钮条（.toc-float-nums 内）。"""
    cls = "snm-nums-list tab-active" if active else "snm-nums-list"
    btns = "\n".join(
        f'<button class="toc-float-num side-nav-btn" data-target="q-{mondai_idx}-{qi}">{qi}</button>'
        for qi in range(1, len(question_labels) + 1)
    )
    return f'<div class="{cls}" data-mondai-idx="{mondai_idx}">{btns}</div>'


# 播放/暂停/循环/设置/关闭这几个图标改用内联 SVG（fill="currentColor"）而不是 emoji 字符
# （▶⏸⚙⟲✕之类）——这些字符在部分移动端浏览器上会被系统符号字体接管渲染，忽略 CSS
# color（表现为图标发灰而不是预期的白色/蓝色）、且字形本身的可视重心跟按钮的 flex
# 居中假设对不上（表现为图标偏离圆心）。SVG 路径取自 Material Design 图标，跨平台
# 渲染结果完全一致，不存在字体兜底的不确定性。
# ICON_PLAY 不在这里定义——播放/暂停图标运行时动态切换（点按钮时用哪个取决于播放
# 状态），这个切换逻辑在共享的 listening-page.js 里，同一份 SVG 常量在那边重复定义
# 了一次，不从这里传过去（这里只放"生成时渲染一次就不再变"的静态图标）。
# 每个 <svg> 都显式带了 width="24" height="24"（等于 viewBox 的自然尺寸），不是纯
# 装饰——真实案例：设置按钮图标改大到 44px 后（对应的 CSS 只有 `.settings-toggle
# svg{width:44px;height:44px}`，没有这两个 HTML 属性），两台不同型号的 iPhone 上
# Safari 实测图标依然停留在很小的尺寸，按钮本身（纯 CSS 控制的 48px 圆形）大小和
# 位置都正确，只有 svg 内部图形没跟着放大——只有 CSS 宽高、没有 HTML 属性宽高时，
# 部分 WebKit 版本对 <svg> 缺 width/height 属性时的内部 viewBox 缩放处理不可靠。
# 显式补上跟 viewBox 一致的 width/height 属性给浏览器一个明确的"原始尺寸"参照，
# CSS 里的 width/height 仍然会按正常层叠规则覆盖它、决定最终显示大小，两者不冲突。
ICON_PAUSE = '<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>'
ICON_GEAR = ('<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M19.14,12.94c0.04-0.3,0.06-0.61,'
             '0.06-0.94c0-0.32-0.02-0.64-0.07-0.94l2.03-1.58c0.18-0.14,0.23-0.41,0.12-0.61l-1.92-3.32'
             'c-0.12-0.22-0.37-0.29-0.59-0.22l-2.39,0.96c-0.5-0.38-1.03-0.7-1.62-0.94L14.4,2.81c-0.04'
             '-0.24-0.24-0.41-0.48-0.41h-3.84c-0.24,0-0.43,0.17-0.47,0.41L9.25,5.35C8.66,5.59,8.12,5.92,'
             '7.63,6.29L5.24,5.33c-0.22-0.08-0.47,0-0.59,0.22L2.74,8.87C2.62,9.08,2.66,9.34,2.86,9.48'
             'l2.03,1.58C4.84,11.36,4.8,11.69,4.8,12s0.02,0.64,0.07,0.94l-2.03,1.58c-0.18,0.14,-0.23,'
             '0.41,-0.12,0.61l1.92,3.32c0.12,0.22,0.37,0.29,0.59,0.22l2.39-0.96c0.5,0.38,1.03,0.7,1.62,'
             '0.94l0.36,2.54c0.05,0.24,0.24,0.41,0.48,0.41h3.84c0.24,0,0.44-0.17,0.47-0.41l0.36-2.54'
             'c0.59-0.24,1.13-0.56,1.62-0.94l2.39,0.96c0.22,0.08,0.47,0,0.59-0.22l1.92-3.32c0.12-0.22,'
             '0.07-0.47-0.12-0.61L19.14,12.94z M12,15.6c-1.98,0-3.6-1.62-3.6-3.6s1.62-3.6,3.6-3.6s3.6,'
             '1.62,3.6,3.6S13.98,15.6,12,15.6z"/></svg>')
ICON_LOOP = ('<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10'
             'H7v-3l-4 4 4 4v-3h12v-6h-2v4z"/></svg>')
ICON_CLOSE = ('<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 '
              '5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>')
# 上一个/下一个/最前/最后导航原来用 «‹›» 这几个字符，实测太细太淡，不容易注意到——
# 换成跟其它按钮一样的实心 SVG 箭头，视觉粗细一致，也更显眼。
ICON_PREV = '<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z"/></svg>'
ICON_NEXT = '<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>'
ICON_FIRST = '<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z"/></svg>'
ICON_LAST = '<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg>'

PAGE_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="robots" content="noindex, nofollow" />
<title>{title}</title>
<link rel="stylesheet" href="/css/listening-page.css">
</head>
<body>

<div id="gate" data-hash="{pwd_hash}">
  <div class="box">
    <h2>&#128274; パスワードを入力してください</h2>
    <input type="password" id="pwdInput" placeholder="パスワード" autofocus />
    <button id="pwdBtn">開く</button>
    <div class="err" id="pwdErr"></div>
  </div>
</div>

<div id="content">
  <div class="sticky-header">
    <div class="sh-title">{title}</div>
    <div class="tab-bar">{tab_buttons}</div>
  </div>

  <nav class="toc" id="sideNav">
    {toc_label_html}
    {side_nav_lists}
  </nav>

  <div class="toc-float" id="sideNavMobile">
    <div class="toc-float-nums">
      <button class="toc-float-toggle" id="snmToggle" title="目次を開く">≡</button>
      {mobile_nums_lists}
    </div>
    <div class="toc-float-panel">
      <div class="toc-float-header"><span>{side_nav_label}</span><button class="toc-float-close" id="snmClose">{ICON_CLOSE}</button></div>
      {side_nav_lists_mobile}
    </div>
  </div>

  <button class="settings-toggle" id="settingsToggle" title="再生設定">{ICON_GEAR}</button>
  <div class="settings-panel" id="settingsPanel">
    <div class="settings-group settings-group-speed">
      <div class="settings-label">再生速度</div>
      <div class="settings-options" id="speedOptions">
        <button class="settings-opt" data-speed="0.5">0.5x</button>
        <button class="settings-opt" data-speed="0.75">0.75x</button>
        <button class="settings-opt active" data-speed="1">1x</button>
        <button class="settings-opt" data-speed="1.2">1.2x</button>
      </div>
    </div>
    <div class="settings-group settings-group-lang">
      <div class="settings-label">表示</div>
      <div class="settings-options" id="langOptions">
        <button class="settings-opt" data-lang="ja">日本語</button>
        <button class="settings-opt active" data-lang="both">日中</button>
        <button class="settings-opt" data-lang="zh">中国語</button>
      </div>
    </div>
  </div>

  <div class="mini-player" id="miniPlayer">
    <button class="mp-btn mp-first" id="mpFirst" title="最初" disabled>{ICON_FIRST}</button>
    <button class="mp-btn mp-prev" id="mpPrev" title="前へ" disabled>{ICON_PREV}</button>
    <button class="mp-btn mp-playpause" id="mpPlayPause" title="再生/一時停止">{ICON_PAUSE}</button>
    <button class="mp-btn mp-next" id="mpNext" title="次へ" disabled>{ICON_NEXT}</button>
    <button class="mp-btn mp-last" id="mpLast" title="最後" disabled>{ICON_LAST}</button>
    <div class="mp-info">
      <div class="mp-scope" id="mpScope">-</div>
      <div class="mp-pos" id="mpPos"></div>
    </div>
    <button class="mp-btn mp-loop" id="mpLoop" title="ループ">{ICON_LOOP}</button>
    <button class="mp-btn mp-stop" id="mpStop" title="停止">{ICON_CLOSE}</button>
  </div>

  <div class="post-page">
    <div class="post-page-header">
      <h1>{title}</h1>
      <p class="post-page-meta">{subtitle}</p>
      <p class="play-hint">▶ 点击题目标题或句子卡片即可播放对应音频</p>
    </div>
    <div class="post-body">
      {sections}
    </div>
  </div>
</div>

<script src="/js/private-gate.js" defer></script>
<script src="/js/listening-page.js" defer></script>

</body>
</html>
'''


def build_sections_html(sentences, questions, audio_rel, quiz_data=None):
    # group sentences by (mondai, question) preserving first-seen order
    by_mondai = []
    mondai_index = {}
    for s in sentences:
        m = s.get("mondai") or "听力材料"
        if m not in mondai_index:
            mondai_index[m] = len(by_mondai)
            by_mondai.append({"mondai": m, "questions": [], "q_index": {}})
        mrec = by_mondai[mondai_index[m]]
        q = s.get("question") or ""
        if q not in mrec["q_index"]:
            mrec["q_index"][q] = len(mrec["questions"])
            mrec["questions"].append({"question": q, "sentences": []})
        mrec["questions"][mrec["q_index"][q]]["sentences"].append(s)

    overview_map = {(q["mondai"], q["question"]): q for q in questions}

    sections = []
    nav_lists = []       # 桌面 .toc 和手机 .toc-float-panel 共用（同一份 <ul> 标记）
    nav_nums_mobile = []  # 手机悬浮收起状态下的数字按钮条
    for mi, mrec in enumerate(by_mondai, 1):
        is_first = (mi == 1)
        q_blocks = []
        q_labels = []
        for qi, qrec in enumerate(mrec["questions"], 1):
            label = qrec["question"] or mrec["mondai"]
            q_labels.append(label)
            meta = overview_map.get((mrec["mondai"], qrec["question"]), {})
            q_blocks.append(question_block_html(
                mi, qi, label,
                meta.get("overview", ""), meta.get("answer", ""),
                qrec["sentences"], audio_rel
            ))
        sections.append(mondai_section_html(mi, mrec["mondai"], "\n".join(q_blocks), is_first))
        nav_lists.append(side_nav_list_html(mi, q_labels, is_first))
        nav_nums_mobile.append(mobile_nums_list_html(mi, q_labels, is_first))

    tab_labels = [mrec["mondai"] for mrec in by_mondai]
    if quiz_data is not None:
        quiz_idx = len(by_mondai) + 1
        sections.append(quiz_section_html(quiz_idx, quiz_data, False))
        nav_lists.append(side_nav_list_html(quiz_idx, [], False))
        nav_nums_mobile.append(mobile_nums_list_html(quiz_idx, [], False))
        tab_labels.append("単語テスト")

    tab_buttons = "\n".join(
        f'<button class="tab-btn{" active" if i == 1 else ""}" data-mondai-idx="{i}">{html.escape(label)}</button>'
        for i, label in enumerate(tab_labels, 1)
    )
    return (
        "\n".join(sections), tab_buttons,
        "\n".join(nav_lists), "\n".join(nav_lists), "\n".join(nav_nums_mobile),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("enriched_json")
    ap.add_argument("out_dir")
    ap.add_argument("--title", required=True)
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--password", help="设置新密码（跟 --password-hash 二选一）")
    ap.add_argument("--password-hash", help="复用已有页面的密码哈希（跟 --password 二选一），"
                     "适合改完边界/文案重新生成页面但密码不用变的场景——不用把明文密码再传一遍")
    ap.add_argument("--quiz-json", help="build_vocab_quiz_data.py 的输出，传了就多生成一个"
                     "「単語テスト」tab（互动出题，不是 seg-card 列表），不传就是普通听力页，"
                     "跟以前完全一样")
    ap.add_argument("--side-nav-label", default="小問", help="桌面侧栏/手机悬浮目录顶部的分类"
                     "标签，默认「小問」（JLPT/会议听力页的問題→小問结构下这个词是对的）。"
                     "教材课文页的侧栏挂的是章节/生词表这类内容，不是「問題」，生成教材页时"
                     "传空字符串 --side-nav-label \"\" 就不显示这个标签，只留列表本身")
    args = ap.parse_args()
    if not args.password and not args.password_hash:
        ap.error("must provide --password or --password-hash")
    if args.password and args.password_hash:
        ap.error("--password and --password-hash are mutually exclusive")

    with open(args.enriched_json, encoding="utf-8") as f:
        data = json.load(f)
    sentences = data["sentences"]
    questions = data.get("questions", [])

    os.makedirs(args.out_dir, exist_ok=True)
    audio_out_dir = os.path.join(args.out_dir, "audio")
    cut_segments(args.audio, sentences, audio_out_dir)

    quiz_data = None
    if args.quiz_json:
        with open(args.quiz_json, encoding="utf-8") as f:
            quiz_data = json.load(f)

    sections, tab_buttons, side_nav_lists, side_nav_lists_mobile, mobile_nums_lists = \
        build_sections_html(sentences, questions, "audio/", quiz_data)
    pwd_hash = args.password_hash or hashlib.sha256(args.password.encode("utf-8")).hexdigest()
    side_nav_label = html.escape(args.side_nav_label)
    toc_label_html = f'<div class="toc-label">{side_nav_label}</div>' if side_nav_label else ""

    page = PAGE_TEMPLATE.format(
        title=html.escape(args.title),
        subtitle=args.subtitle,
        sections=sections,
        tab_buttons=tab_buttons,
        side_nav_lists=side_nav_lists,
        side_nav_lists_mobile=side_nav_lists_mobile,
        mobile_nums_lists=mobile_nums_lists,
        toc_label_html=toc_label_html,
        side_nav_label=side_nav_label,
        pwd_hash=pwd_hash,
        ICON_PAUSE=ICON_PAUSE,
        ICON_GEAR=ICON_GEAR,
        ICON_LOOP=ICON_LOOP,
        ICON_CLOSE=ICON_CLOSE,
        ICON_PREV=ICON_PREV,
        ICON_NEXT=ICON_NEXT,
        ICON_FIRST=ICON_FIRST,
        ICON_LAST=ICON_LAST,
    )

    out_html = os.path.join(args.out_dir, "index.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"Wrote {out_html} and {len(sentences)} audio clips to {audio_out_dir}")


if __name__ == "__main__":
    main()
