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
    # 々（叠字符号，U+3005，比如"少々""人々""次々"）不在 CJK 表意文字主区块
    # 里，但它在读音上等同于"重复前一个汉字"，furigana 拆分要把它当汉字一样
    # 对待——真实案例（textbook-sjp-zg-l10，"少々"）：不算进来的话，_split_
    # kana_segments() 会把它误判成普通送假名字符，结果两个字都读不出音（"少"
    # 找不到读音，"々"本来就不是假名，hira 里也搜不到它，兜底成两个都不注音）。
    return '一' <= ch <= '鿿' or ch == '々'


def _needs_kana_annotation(text):
    """判断这个词自己的原文能不能让读者看出读音——汉字读不出来需要注音，这个
    没有争议；但纯罗马字/数字（比如生词"DVD"，读音"ディーブイディー"）同样
    看着原文猜不出日语读音，跟汉字是同一类问题。真实案例（textbook-sjp-zg-l12）：
    "DVD"这条生词表里填了 kana="ディーブイディー"，但 sentence_to_data() 的
    kana 覆盖分支只在 `any(_is_kanji(...))` 时才生成 <ruby> 注音，DVD 没有汉字，
    这个判断直接漏掉，读音被悄悄丢弃，页面上只显示"DVD"三个字母、完全没有
    注音提示。纯假名/纯片假名词条不算在内——假名本身就是表音文字，照原文就能
    读出来，不需要再注一遍。"""
    return any(_is_kanji(ch) or (ch.isascii() and ch.isalnum()) for ch in text)


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
    # "5日"是日期特殊读法いつか（不是ごにち），跟"20日"→はつか同一类坑，只在
    # "5"后面才触发，不影响"1日"(いちにち)/"3日"(みっか)这些其它数字+日的组合。
    ("5", "日"): "いつか",
}
# _split_kana_segments() 定位"汉字读音在哪结束、送假名从哪开始"时，靠"这个
# 汉字至少占几拍"这个下限往后跳过对应字符数再搜索送假名的锚点字符（见那个
# 函数内部的详细注释）——默认假设每个汉字字符至少1拍，对绝大多数单字训读
# 够用，但有些常见汉字单字训读本身就有2拍以上，如果这个字读音的最后一拍
# 恰好跟紧跟着的送假名首字符相同，默认的"至少1拍"下限不够，会在还没搜出
# 这个字真实读音之前就撞见这个假字符、误判读音提前结束。真实案例
# （textbook-sjp-zg-l12，"低く"）："低"训读ひく是2拍，但默认下限只保证跳过
# 1拍，搜索"く"这个锚点时在第1拍位置就已经撞见"低"自己读音里的"く"，导致
# "低"的注音被错误截断成"ひ"（正确应为"ひく"，"低"读音里的"く"被误判成
# 送假名的一部分）。这张表记录已知会撞上这个坑的单字训读，`_split_kana_
# segments()` 算下限时优先查这张表，查不到的字才退回"至少1拍"的默认假设——
# 不是每个2拍字都要收录（比如"高"→たか同样2拍，但目前没有在任何真实句子里
# 撞上这个坑，不用未卜先知地收录进来），只有真的观察到撞车才加。
_KANJI_MIN_MORA = {
    "低": 2,
    # "色"训读いろ是2拍，真实案例（textbook-sjp-zg-l14，"茶色い"）：默认下限
    # 只保证跳过1拍，搜索送假名"い"这个锚点时在第1拍位置（"ちゃいろ"的
    # "い"，恰好是"色"自己读音"いろ"的第一拍）就已经撞见，导致"茶色"的注音
    # 被错误截断成"ちゃ"（正确应为"ちゃいろ"）。
    "色": 2,
}


_TOKEN_READING_OVERRIDES_UNCONDITIONAL = {
    "入っ": "はいっ",
    # 人名"千尋"（比如《千と千尋の神隠し》的女主角）该读ちひろ，pykakasi 按
    # 通用音读猜成せんじん——这类专有名词的正确读音本来就不是"看上下文规律"
    # 能推出来的，得靠具体知识判断，是这个覆盖表里少数几个"必须无条件覆盖"
    # 的场景之一（"千尋"作为人名比作为普通词的用法常见得多，不太会有需要
    # 保留せんじん这个读音的场景）。
    "千尋": "ちひろ",
    # "今日は"紧跟在一起时 pykakasi 会当成寒暄语"こんにちは"整词匹配，但这个
    # token 绝大多数时候其实是"今日"(今天)+"は"(助词)两个独立成分连写（比如
    # "今日は遠慮しておきます"＝"今天就不叨扰了"），该读きょうは——寒暄语场景
    # 现代日语几乎总是直接写假名"こんにちは"，很少会用"今日は"这个汉字写法，
    # 无条件覆盖不容易误伤真正的寒暄语用法。
    "今日は": "きょうは",
    # "日本"孤立成词时 pykakasi 默认读にっぽん，但日常会话/书面语里更通用、更
    # 自然的读法是にほん（"日本語"＝にほんご这类复合词 pykakasi 本来就读对了，
    # 只有孤立的"日本"两个字单独成 token 时才会读成にっぽん，两者不一致）。
    "日本": "にほん",
    # "怒ら"（"怒る"未然形，比如"怒られた"＝被骂/被惹怒）pykakasi 默认读いから
    # （对应読音いかる，偏文语/激烈的"愤怒"语感），但日常叙述"被骂/生气"这个
    # 场景绝大多数该读おこる——"怒られた"该读おこられた。
    "怒ら": "おこら",
    # "万人"pykakasi 固定合并成一个 token 整体读ばんにん，但"万"在"〜万人"这个
    # 统计场景（"7,550万人""1万人"这类数字紧跟"万人"）里几乎总是该读まんにん
    # （ばん是"万"的罕见读音，比如"万暦"这类专有名词才用得上）。真实案例
    # （textbook-sjp-zg-l13，人口统计课文）：audit_furigana.py 高危字扫描之外
    # 意外发现的（"万"本身不在危险字表里，是逐句人工核对读音时顺手用 pykakasi
    # 直接测试"万人"这个词才确认的），不限定 prev_orig 无条件覆盖——没找到
    # "万人"该读ばんにん的真实场景，跟"日本"→"にほん"是同一类可以放心无条件
    # 覆盖的情况。
    "万人": "まんにん",
    # "君"孤立成词时 pykakasi 默认读くん（人名后缀，比如"田中くん"——但那种
    # 场景"君"会紧跟在具体人名后面），教材对话里"君"绝大多数是独立用作第二
    # 人称代词"你"（きみ，比如"君の頼みだ""君と町子さんが出会った"），くん
    # 后缀用法反而需要紧跟一个具体人名，从没在这几课的真实内容里出现过。
    # 跟"日本"→"にほん"同一类可以无条件覆盖的情况——真遇到"名字+君(くん)"
    # 这种搭配再改成按 prev_orig 判断的条件规则，不要未卜先知地先加。
    "君": "きみ",
    # 人名"李"（中文姓氏，比如"上海の李さん"）该读り，pykakasi 按训读猜成
    # すもも（"李子"这种水果的訓読，日常词汇里很少用到"李"这个字，多数场景
    # 就是作为人名出现），跟"千尋"→"ちひろ"同一类必须无条件覆盖的专有名词
    # 读音坑，没有"李"该读すもも的真实场景。
    "李": "り",
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
    # 汉字数量单位（万/億/兆……）同样算"数字"——真实案例（textbook-sjp-zg-l13，
    # 人口统计课文"65億人"）：pykakasi 自己对"人"的默认读音本来就是对的
    # （にん，紧跟在"億"后面的计数语境），但这条规则原来只认阿拉伯数字，
    # "億"的最后一个字符不是数字，`prev_ends_with_digit` 判成 False，反而把
    # pykakasi 已经猜对的にん覆盖回错误的ひと——**这条规则设计的初衷是"补救
    # pykakasi 对孤立单字人的默认误判"，结果在这个场景里适得其反地把正确
    # 默认值改错了**，用户在编辑模式里手动改回にん才发现。
    prev_ends_with_digit = bool(prev_orig) and (
        prev_orig[-1].isdigit() or prev_orig[-1] in "十百千万億兆"
    )
    # "1人"/"2人"是不规则读法ひとり/ふたり（不是常规的いちにん/ににん），只有
    # 汉数字写法"一人"/"二人"pykakasi 自己的词典本来就读对（会整体合并成一个
    # token，不会拆成"一"+"人"两段，不受这条规则影响），阿拉伯数字写法"1人"/
    # "2人"会被拆成独立的"人"token、默认读成にん，是错的。真实案例
    # （textbook-sjp-zg-l13，人口统计课文"1人の女性が出産する子供の数"）：
    # Whisper 转写这句实际发音时自动写成了汉字"一人"（转写模型对常见词有
    # 自己的用字习惯，这一点间接印证了真实发音是ひとり而不是いちにん）。
    # 3人及以上没有这个不规则读法，仍然走下面的にん/じん默认规则。
    if orig == "人" and prev_orig == "1":
        return "ひとり"
    if orig == "人" and prev_orig == "2":
        return "ふたり"
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
    # "間"跟"人"/"位"是同一类坑：pykakasi 给孤立的"間"字默认读かん，但那其实是
    # "1週間""3日間"这类"数字+間"时长量词专用的读法——真正常见的场景是"間"作为
    # 独立名词表示"期间/之间"（比如"いる間です""その間""休み時間の間"），这种
    # 该读あいだ。跟"人"同理用"prev_orig 是不是数字结尾"判断：数字后面的"間"是
    # 量词读かん，其它情况（动词连体形/の/その 等后面）是独立名词读あいだ。
    # （"週間""時間""期間"这类固定复合词 pykakasi 自己会合并成一个 token，不会
    # 拆成独立的"間"字，不受这条规则影响。）
    if orig == "間":
        return "かん" if prev_ends_with_digit else "あいだ"
    # "歳"跟"人"/"位"/"間"是同一类坑：孤立的"歳"字 pykakasi 默认给とし（"お歳を
    # 伺う"这种问年龄的场景确实读とし），但紧跟在数字后面表示年龄量词时该读
    # さい（"25歳"=にじゅうごさい）——真实案例（textbook-sjp-zg-l13，人口统计
    # 课文"1977年には25.0歳であったが，1992年には26.0歳"）：三处"N.N歳"全部被
    # 读成とし，是错的，用户逐句人工核对时发现。跟"人"同理，只在没有紧跟数字时
    # 保留pykakasi的とし默认值。"20歳"这个特例读はたち，跟"20日"=はつか同一类
    # 不规则读法，目前没有真实句子踩到，暂不处理，真遇到再加进
    # `_TOKEN_READING_OVERRIDES_BY_PREV`。
    if orig == "歳" and prev_ends_with_digit:
        return "さい"
    # "の日"（"〜的那天"，比如"休みの日""雨の日""楽しい日"）孤立成词该读ひ，
    # 跟已有的 ("その","日")→"ひ" 是同一类坑，只是前面接的是"の"而不是"その"——
    # 真实案例（textbook-sjp-zg-l14，"せっかくのお休みの日に"）：pykakasi 默认
    # 给孤立的"日"字读にち（"〜日"计数/复合词读法，比如"三日""日曜日"），但
    # "Nの日"这个"表示某一天"的独立名词用法几乎总是该读ひ，跟"その日"是同一条
    # 通用规律（"の"前面究竟是什么词不重要，只要紧跟在"の"后面单独成词就该读
    # ひ），直接按 prev_orig 是不是"の"判断，不用像"その日"那样局限于固定搭配。
    if orig == "日" and prev_orig == "の":
        return "ひ"
    # "後にする"（推迟，往后放）这个惯用语里的"後"该读あと，pykakasi 默认给
    # 孤立的"後に"读のちに（"後に"单独作副词"之后/随后"时确实两种读音都存在，
    # 跟"その後"是同一类歧义——但"〜を後にして/にした/にします"这个固定惯用语
    # 只有あとに这一种读法，のちに在这个搭配里不成立）。真实案例
    # （textbook-sjp-zg-l14，"そんなあいさつは後にして，とにかく上がって"）：
    # 用next_char是不是"し"（"して/した/します"这几个后续活用形的共同起始假名）
    # 判断是不是这个惯用语，不影响"後に，"这类真正表示"之后"的独立副词用法。
    if orig == "後に" and next_char == "し":
        return "あとに"
    # "1次/2次/3次"这类"数字+次"表示"第N次/第N轮"时该读じ（一次試験=いちじしけん），
    # 跟"人/位/間/歳"是同一类坑：孤立的"次"字 pykakasi 默认给つぎ（"次の駅"这种
    # 表示"下一个"的独立名词用法确实读つぎ，但那时前面不会紧跟数字），紧跟在
    # 数字后面表示顺序量词时该读じ。真实案例（textbook-sjp-zg-l14，"1次試験，
    # 2次試験，3次試験"）：三处全部被读成つぎ，是错的。
    if orig == "次" and prev_ends_with_digit:
        return "じ"
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


def _kata_to_hira_char(ch):
    """把片假名字符转成对应的平假名——片假名和平假名在 Unicode 里是平行区块，
    对应字符之间固定偏移0x60（比如"ア"U+30A2对"あ"U+3042），标准片假名范围
    （U+30A1~U+30F6，涵盖长音符ー之外的全部假名）直接减0x60即可，其它字符
    原样返回。"""
    code = ord(ch)
    if 0x30A1 <= code <= 0x30F6:
        return chr(code - 0x60)
    return ch


def _split_kana_segments(orig, hira):
    """把一个"汉字+送假名"混合 token 拆成交替的 [{"text":汉字串,"kana":读音}, {"text":
    送假名串}, ...] 段列表——正确的排版规范是只给每一段连续汉字标注读音，中间/
    结尾已经是假名的部分照抄显示，不用在 <rt> 里重复一遍。

    这个函数取代了原来的 `_split_trailing_kana()`（只会从结尾摘送假名，摘到
    第一个汉字就停）——那个版本只能处理"一段汉字+结尾送假名"这一种形状（比如
    "悪かった"/"比べ"），遇到"汉字+中间送假名+汉字+结尾送假名"这种有多段汉字
    的词（比如"書き間違える" = 書+き+間違+える）就会出错：从结尾摘到"違"字
    （汉字）就停手，中间的送假名"き"没被摘出来，被错误地跟前面的"書"、后面的
    "間違"一起并进同一个 <rt> 注音里，显示成"書き間違"整体标读音"かきまちが"
    （虽然读音字符本身没错，但排版上把不该注音的"き"也框进了注音范围）。真实
    案例（textbook-sjp-zg-l12，"書き間違える"）：用户反馈期望是拆成两段独立
    注音"書→か"和"間違→まちが"，"き"和"える"照原样显示，不应该合并成一段。

    算法：把 orig 按"连续汉字"/"连续非汉字"分组（相邻同类字符归并成一组，
    两类必然交替出现）。非汉字组本身就是假名，天然知道自己在 hira 里对应哪段
    （逐字符原样出现）——用非汉字组的首字符去 hira 里搜索定位，搜到的位置
    之前那一段就是紧邻的前一个汉字组的读音。整段 orig 全是汉字（熟字训，比如
    "女将"→"おかみ"，没有任何送假名可以当定位锚点）或者整段全是非汉字（比如
    纯罗马字生词"DVD"→"ディーブイディー"，没有汉字可拆）这两种退化情况，
    直接整体当一段处理，不拆。

    非汉字组如果是片假名（比如"口コミ"的"コミ"、"キリスト教"的"キリスト"），
    hira 里存的读音是平假名，片假名字符不会字面出现在 hira 里，直接拿片假名
    字符去 hira.find() 搜是搜不到的——用 `_kata_to_hira_char()` 把搜索用的
    首字符转成对应平假名再搜，搜到的位置照样是正确的边界（片假名/平假名是
    同一套假名的两种写法，字符数量、顺序都一一对应，只有搜索这一步需要转换，
    最终塞进 segment 里的还是原始片假名文本，不影响显示）。

    "〜"（语法笔记里表示"接在词干后面"的占位符，比如"〜性""同〜"）是完全
    不发音的符号，字面上不会出现在 hira 里，也不占用任何一个假名音——不能
    当成普通非汉字组处理（会被误判成"hira 里找不到这个字符"从而放弃给相邻
    汉字注音，真实案例：textbook-sjp-zg-l11 的"〜性"/"せい"，"性"完全没标
    读音）。处理方式：先把"〜"占位组从分组序列里过滤掉，用剩下的"正常"分组
    跑一遍同样的锚点定位算法算出每一段汉字的读音，最后再按原始分组顺序把
    结果和"〜"占位段重新交错拼回去——两遍处理是必须的，不能在第一遍顺手
    处理，因为"〜"可能出现在待定汉字读音**结算之前**（比如"同〜"，"同"的
    读音要等到整个 orig 处理完才能结算出来，如果这时候顺手把"〜"也塞进
    segments，输出顺序会变成"〜"排在"同"前面，跟原文顺序颠倒）。"""
    if orig == hira:
        return [{"text": orig}]
    groups = []
    for ch in orig:
        is_kanji = _is_kanji(ch)
        if groups and groups[-1][0] == is_kanji:
            groups[-1] = (is_kanji, groups[-1][1] + ch)
        else:
            groups.append((is_kanji, ch))
    kanji_groups = [g for g in groups if g[0]]
    if not kanji_groups or len(kanji_groups) == len(groups):
        # 退化情况：整段没有汉字（罗马字/数字类词），或者整段全是汉字（熟字训，
        # 没有送假名可当定位锚点）——都没法按分段对齐，整体当一段注音。
        return [{"text": orig, "kana": hira}]

    filtered = [g for g in groups if g[0] or g[1] != "〜"]
    kanji_readings = []
    hira_pos = 0
    pending_kanji = None
    for is_kanji, gtext in filtered:
        if is_kanji:
            pending_kanji = gtext
            continue
        if pending_kanji is not None:
            # 找这段送假名的第一个字符在 hira 里的位置，来定位前一段汉字读音的
            # 结束点——不能直接从 hira_pos 开始裸搜，每个汉字至少占几拍（默认
            # 假设1拍，_KANJI_MIN_MORA 表里登记过的字用登记的拍数，见那张表的
            # 注释），搜索起点至少要跳过这些拍数对应的字符数，否则送假名首字符
            # 如果刚好和汉字读音的某一拍相同（比如"聞き"，聞→き，紧跟着送假名
            # 也是"き"，hira="ききまちが"；或者"低く"，低→ひく最后一拍是"く"，
            # 紧跟着送假名也是"く"），裸搜索会在还没跳过这个字真实读音之前就
            # 撞见这个假字符，误判读音提前结束。真实案例（textbook-sjp-zg-l12，
            # "聞き間違える"/"低く"）：前者"聞"丢了读音、"間違"读音里多了个
            # "き"；后者"低"的注音被错误截断成"ひ"（正确应为"ひく"）。
            anchor_char = _kata_to_hira_char(gtext[0])
            min_mora = sum(_KANJI_MIN_MORA.get(ch, 1) for ch in pending_kanji)
            min_start = hira_pos + max(1, min_mora)
            idx = hira.find(anchor_char, min_start)
            if idx == -1:
                idx = hira.find(anchor_char, hira_pos)
            if idx == -1:
                # 兜底：hira 里找不到这个假名字符（读音订正表把读音改得跟表面
                # 字符对不上之类的边界情况），放弃细分，保守地不给这段汉字注音，
                # 总比崩掉强——真出现这种情况应该是订正表本身有问题，需要人工
                # 回头核实，不是这个函数该默默"修好"的。
                kanji_readings.append(None)
                idx = hira_pos
            else:
                kanji_readings.append(hira[hira_pos:idx])
            hira_pos = idx
            pending_kanji = None
        hira_pos += len(gtext)
    if pending_kanji is not None:
        kanji_readings.append(hira[hira_pos:] or None)

    segments = []
    ki = 0
    for is_kanji, gtext in groups:
        if is_kanji:
            reading = kanji_readings[ki]
            ki += 1
            segments.append({"text": gtext, "kana": reading} if reading else {"text": gtext})
        else:
            segments.append({"text": gtext})
    return segments


def _split_plain_by_char_times(text, times):
    """把一段不带汉字读音的纯文本（送假名、或者整段没有汉字的 token，比如
    一长串"ということになりました"这样的助词/助动词连读）按 char_times
    "连续相同时间戳算一组"拆成更细的跟读高亮单元列表 [(子串, 时间戳), ...]。

    真实案例（用户反馈）：跟读模式下有的高亮一次盖住近十个假名，是因为
    tokenize_ja() 原来"一个 pykakasi 分词结果=一个跟读高亮单元"，纯假名的
    长串（pykakasi 常把好几个助词/助动词粘成一个不可再分的 token）就只有
    一个时间戳、一整段一起亮。但 refine_boundaries.py 的 align_group() 算
    char_times 时早就注释过："Whisper 给日语打的词级时间戳本来就接近逐字/
    逐音节粒度"——也就是说这段长文字底下其实已经有好几个不同的真实时间戳，
    只是 tokenize_ja() 只挑了第一个字符的时间戳、把后面的全丢了。这个函数
    把这份本来就有的细粒度数据重新利用起来，同一个时间戳对应的连续字符
    合并成一个高亮单元，时间戳变化的地方就该断开成新的单元。

    `times` 是跟 `text` 等长的时间戳列表（元素可以是 None，表示这个字符
    没有可用时间戳，比如 char_times 数组比句子本身短的边界情况）——如果
    长度对不上或者整个没有时间戳数据，直接整段不拆当一个单元返回（没有
    更细的数据可用，没法拆，保底行为等同于拆分前）。"""
    if not times or len(times) != len(text):
        return [(text, times[0] if times else None)]
    runs = []
    start = 0
    for i in range(1, len(text) + 1):
        if i == len(text) or times[i] != times[start]:
            runs.append((text[start:i], times[start]))
            start = i
    return runs


def tokenize_ja(text, char_times=None):
    """假名注音分词——把日语原文按 pykakasi 分词、套用读音订正表
    （_TOKEN_READING_OVERRIDES_*/_resolve_hira）、拆分送假名（_split_kana_segments），
    返回一个"扁平化 token 列表"，每个 token 是一个 dict：
      {"text": 这个 token 的原文, "kana": 假名读音（可选，只在需要标注且跟 text
       不同时才有）, "t": 跟读高亮用的绝对时间戳（可选，只在传了 char_times 且
       这个 token 有实际可读内容时才有）}
    换行符单独表示成 {"text": "\\n"}（渲染时转成 <br>，不参与 ruby/高亮）。

    这是原来 ruby_html() 的核心逻辑，拆出来单独返回结构化数据（而不是直接拼好
    的 HTML 字符串）——data-driven 页面（--data-driven，见 build_lesson_data()）
    把这份数据序列化进 data.js，前端渲染器（docs/js/page-renderer.js）只需要
    做简单模板拼接（token 有 kana 就包一层 <ruby>，有 t 就包一层
    <span class="tw" data-t="...">），不用在 JS 里重新实现这里的分词/读音订正/
    送假名拆分——这些逻辑复杂且经过多轮真实案例订正（见本文件开头的
    _TOKEN_READING_OVERRIDES_*/_resolve_hira/_split_kana_segments 注释），只应该
    存在一份、只应该在生成时（Python，有 pykakasi 可用）跑一次。
    """
    out = []
    lines = text.split("\n")
    char_idx = 0
    for li, line in enumerate(lines):
        tokens = _kks.convert(line)
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
            # 这个 token 自己的逐字符时间戳切片（跟 orig 等长，越界的位置填
            # None）——之前只挑第一个字符的时间戳给整个 token 用，这里保留
            # 全部，供下面按汉字段/纯假名段分别细化跟读高亮粒度。
            if char_times is not None:
                tok_times = [
                    char_times[char_idx + i] if char_idx + i < len(char_times) else None
                    for i in range(tok_len)
                ]
            else:
                tok_times = None
            char_idx += tok_len
            # 标点/符号（「、」「。」「?」之类）不算"读到的词"，不参与跟读高亮——
            # pykakasi 分词里纯标点 token 没有假名/汉字，isalnum() 全假，用这个判断跳过。
            has_content = any(ch.isalnum() for ch in orig)
            if not has_content:
                out.append({"text": orig})
            elif any(_is_kanji(ch) for ch in orig) and hira != orig:
                offset = 0
                for seg in _split_kana_segments(orig, hira):
                    seg_len = len(seg["text"])
                    seg_times = tok_times[offset:offset + seg_len] if tok_times is not None else None
                    offset += seg_len
                    if any(_is_kanji(ch) for ch in seg["text"]):
                        # 汉字段（带读音注音的那部分）当一个高亮单元，不再往下拆——
                        # 一个汉字/复合词的读音是一起念出来的，跟读高亮按"这个读音
                        # 开始的时刻"整体点亮才符合直觉，细拆到单字反而不自然。
                        entry = dict(seg)
                        if seg_times and seg_times[0] is not None:
                            entry["t"] = round(seg_times[0], 2)
                        out.append(entry)
                    else:
                        # 送假名（比如"える"）不带读音注音，可以放心按 char_times
                        # 里的真实分段细化，不用担心切碎了破坏 <ruby> 的显示。
                        for sub_text, sub_time in _split_plain_by_char_times(seg["text"], seg_times):
                            entry = {"text": sub_text}
                            if sub_time is not None:
                                entry["t"] = round(sub_time, 2)
                            out.append(entry)
            else:
                for sub_text, sub_time in _split_plain_by_char_times(orig, tok_times):
                    entry = {"text": sub_text}
                    if sub_time is not None:
                        entry["t"] = round(sub_time, 2)
                    out.append(entry)
        if li < len(lines) - 1:
            out.append({"text": "\n"})
            char_idx += 1  # 换行符本身也占一个字符位，对齐 char_times 的下标

    # 收尾合并：上面按 char_times 细分是"在每个 pykakasi 分词内部"做的，不会
    # 跨分词边界合并——但 pykakasi 偶尔会把同一个 Whisper 识别词从中间断开
    # 成两个分词（真实案例：「分からない」被 pykakasi 切成"分か"/"らないこ
    # とがあるものですね"两段，"から"这两个字恰好一个在前一段末尾、一个在
    # 后一段开头，但 char_times 显示这两个字享有完全相同的时间戳，说明
    # Whisper 识别成的是同一个词）。这种情况如果不处理，"から"会被拆成两个
    # 独立的跟读高亮点，明明是同一个词却分两次点亮，观感上比"没拆开"更奇怪。
    # 收尾这一步把相邻的两个"纯文本段（没有 kana 注音）"在共享同一个真实
    # 时间戳时合并回一段——只合并没有汉字读音的部分（有 <ruby> 注音的段落
    # 不参与合并，见上面"汉字段当一个高亮单元不再往下拆"的注释，避免破坏
    # 已经处理好的读音标注范围），且只在两边的 t 都存在且相等时才合并（没有
    # 时间戳的段落之间不能瞎合并，那样会把本来就是两个不相关分词的文字粘
    # 一起，跟这次要修的问题背道而驰）。
    merged = []
    for entry in out:
        if (merged and "kana" not in entry and "kana" not in merged[-1]
                and entry["text"] != "\n" and merged[-1]["text"] != "\n"
                and entry.get("t") is not None and merged[-1].get("t") == entry.get("t")):
            merged[-1] = {"text": merged[-1]["text"] + entry["text"], "t": merged[-1]["t"]}
        else:
            merged.append(entry)
    return merged


def ruby_html_from_tokens(tokens):
    """把 tokenize_ja() 的输出拼成 HTML 字符串——原来 ruby_html() 直接拼字符串
    的那部分逻辑，拆出来复用，保证"生成完整 HTML 的旧流程"和"生成 data.js 给
    前端渲染器用的新流程"读的是同一份分词结果，不会出现两条路径读音不一致。"""
    parts = []
    for tok in tokens:
        text = tok["text"]
        if text == "\n":
            parts.append("<br>")
            continue
        kana = tok.get("kana")
        inner = f'<ruby>{text}<rt>{kana}</rt></ruby>' if kana and kana != text else text
        if "t" in tok:
            parts.append(f'<span class="tw" data-t="{tok["t"]:.2f}">{inner}</span>')
        else:
            parts.append(inner)
    return ''.join(parts)


def ruby_html(text, char_times=None):
    """假名注音渲染（旧接口，非 data-driven 页面仍在用）。有 char_times（
    refine_boundaries.py 用词级时间戳文本对齐算出来的、这句里每个字符对应的
    绝对播放时间）时，额外给每个分词包一层 `<span class="tw" data-t="...">`，
    播放时前端按 audio.currentTime 找到当前应该高亮的词。没有 char_times（
    简单流程没跑 refine_boundaries.py，或者这句对齐质量太差被跳过）就退化成
    纯 <ruby> 输出，不带高亮能力——静态展示效果不受影响，只是没有跟读高亮。
    """
    return ruby_html_from_tokens(tokenize_ja(text, char_times))


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
<link rel="icon" href="/favicon.ico">
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

# data-driven 页面用的壳模板——跟 PAGE_TEMPLATE 骨架完全一样（密码门/吸顶栏/
# 悬浮播放器/设置面板这些固定 UI 不变），区别只在于 {tab_buttons}/{side_nav_lists}/
# {mobile_nums_lists}/{side_nav_lists_mobile}/{sections} 这几处不再是生成时算好的
# HTML，换成空容器（带 id，给 page-renderer.js 定位用），内容由 data.js +
# page-renderer.js 在浏览器里渲染出来。page-renderer.js 必须排在 listening-page.js
# 前面（都是 defer script，会按文档顺序依次执行）——等 listening-page.js 那些
# `document.querySelectorAll(".seg-card")` 之类的查询跑起来时，DOM 必须已经渲染好，
# 不然会查到空结果，所有交互都不会生效。
#
# edit-mode-restore.js **不带 defer**，紧跟在 <script src="data.js"> 后面——
# 要在 page-renderer.js（defer，稍后才跑）渲染页面之前，把编辑模式暂存在
# localStorage 里的修改先合并进 window.LESSON_DATA，不然用户上次在页面里编辑
# 过的内容刷新一次就"消失"了（其实是暂存数据还在，只是渲染时用的是没合并
# 编辑的旧数据）。edit-mode.js（defer，给每张卡片加 ✎ 编辑图标+编辑弹窗）
# 排在 page-renderer.js 后面——卡片必须先被渲染出来，才能挂编辑图标上去。
SHELL_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="robots" content="noindex, nofollow" />
<title>{title}</title>
<link rel="icon" href="/favicon.ico">
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
    <div class="tab-bar" id="tabBar"></div>
  </div>

  <nav class="toc" id="sideNav">
    {toc_label_html}
    <div id="sideNavLists"></div>
  </nav>

  <div class="toc-float" id="sideNavMobile">
    <div class="toc-float-nums">
      <button class="toc-float-toggle" id="snmToggle" title="目次を開く">≡</button>
      <div id="mobileNumsLists"></div>
    </div>
    <div class="toc-float-panel">
      <div class="toc-float-header"><span>{side_nav_label}</span><button class="toc-float-close" id="snmClose">{ICON_CLOSE}</button></div>
      <div id="sideNavListsMobile"></div>
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
    <div class="post-body" id="postBody"></div>
  </div>
</div>

<script src="data.js"></script>
<script src="/js/edit-mode-restore.js"></script>
<script src="/js/page-renderer.js" defer></script>
<script src="/js/edit-mode.js" defer></script>
<script src="/js/private-gate.js" defer></script>
<script src="/js/listening-page.js" defer></script>

</body>
</html>
'''


def _group_by_mondai_question(sentences, questions):
    """按 (mondai, question) 分组，保留首次出现的顺序，附带每道题的
    overview/answer——这份分组结构是 build_sections_html()（生成完整 HTML）
    和 build_lesson_data()（生成 data-driven 用的 JSON 数据）共用的，两条
    路径分组逻辑必须完全一致，所以只写一份。"""
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
    for mrec in by_mondai:
        for qrec in mrec["questions"]:
            meta = overview_map.get((mrec["mondai"], qrec["question"]), {})
            qrec["overview"] = meta.get("overview", "")
            qrec["answer"] = meta.get("answer", "")
    return by_mondai


def sentence_to_data(s, audio_rel, quiz_by_id=None):
    """把一句 sentence 转成 data-driven 页面用的结构化数据（page-renderer.js
    渲染 .seg-card 用）——跟 sentence_card_html() 是同一份信息，只是不拼成
    HTML 字符串，改成前端能直接用的 dict。char_times 的绝对时间戳→音频文件
    内部相对时间的换算、token 化都复用跟旧路径完全相同的函数
    （tokenize_ja()），保证两条路径读音/高亮时间戳一致。
    生词条目没有 char_times（单词粒度不做逐字符跟读高亮），这种情况下如果
    词条自己填了 `kana`（覆盖读音，见 build_vocab_from_wordlist.py 的
    furigana_for()），用这个读音而不是跑 tokenize_ja() 自动分词——pykakasi
    对熟字训/专有名词容易读错，`kana` 存在就是为了绕开自动转换，这里也要
    尊重这个覆盖，不能又走回自动分词。但送假名（比如"比べ"的"べ"、"悪かった"
    的"かった"、"書き間違える"中间的"き"）仍然要用 `_split_kana_segments()`
    拆出来，只给每一段汉字本体标读音——不拆的话会把"比べ"整个包进
    `<ruby>`，注音显示"くらべ"盖住"比べ"两个字，而不是只给"比"注"くら"、
    "べ"照原样显示；这条规则跟 tokenize_ja()
    内部处理自动分词结果时完全一样，`kana` 覆盖只是免掉了自动分词/读音猜测
    这一步，排版规范不能因为走的是覆盖分支就不一样。没有 char_times 也
    没有 `kana` 的普通句子（简单流程没跑 refine_boundaries.py）才退回
    tokenize_ja(text)（不传 char_times，token 不带 t 字段，没有跟读高亮但
    假名注音仍然正确）。"""
    char_times = s.get("char_times")
    rel_char_times = [round(t - s["start"], 2) for t in char_times] if char_times else None
    if rel_char_times:
        tokens = tokenize_ja(s["text"], rel_char_times)
    elif s.get("kana"):
        text, kana = s["text"], s["kana"]
        if _needs_kana_annotation(text) and kana != text:
            tokens = _split_kana_segments(text, kana)
        else:
            tokens = [{"text": text}]
    else:
        tokens = tokenize_ja(s["text"])
    blanks = s.get("blanks") or []
    quiz_sentence = None
    # 生词卡片本身只有孤立的一个词，没有上下文——切到"填空"练习模式时，
    # 与其把整个词自己挖空（等于直接把卡片内容全部藏起来，没有意义），不如
    # 借用单词测试里已经准备好的例句+挖空位置（quiz_data 里同一个 id 的
    # `sentence`/`blank` 字段，跟单词测试自己的"填空题"题型用的是同一份
    # 数据）。真实需求：用户反馈"生词的填空模式，能不能采用对应单词测试中
    # 的填空题"——生词条目本来就没有自己的 `blanks`（一直是空数组），这里
    # 用 quiz 例句反推出来，不会跟内容作者手写的 `blanks` 冲突。
    if quiz_by_id and not blanks:
        quiz_entry = quiz_by_id.get(s["id"])
        if quiz_entry and quiz_entry.get("sentence") and quiz_entry.get("blank"):
            blanks = [quiz_entry["blank"]]
            quiz_sentence = quiz_entry["sentence"]
    result = {
        "id": s["id"],
        "speaker": s.get("speaker"),
        "speakerKana": s.get("speaker_kana"),
        "tokens": tokens,
        "zh": s["zh"],
        "notes": s.get("notes") or "",
        "blanks": blanks,
        "audio": f"{audio_rel}seg-{s['id']:03d}.mp3",
    }
    if quiz_sentence:
        result["quizSentence"] = quiz_sentence
    return result


def build_lesson_data(title, subtitle, side_nav_label, sentences, questions, audio_rel, quiz_data=None):
    """data-driven 页面的完整数据——序列化进 data.js，page-renderer.js 读这份
    数据在浏览器里渲染出页面骨架（tab栏/侧栏目录/mondai-section/question-block/
    seg-card），结构上跟 build_sections_html() 生成的 HTML 是一一对应的。"""
    by_mondai = _group_by_mondai_question(sentences, questions)
    quiz_by_id = {q["id"]: q for q in quiz_data} if quiz_data else None
    tabs = [
        {
            "mondai": mrec["mondai"],
            "questions": [
                {
                    "question": qrec["question"],
                    "overview": qrec["overview"],
                    "answer": qrec["answer"],
                    "sentences": [sentence_to_data(s, audio_rel, quiz_by_id) for s in qrec["sentences"]],
                }
                for qrec in mrec["questions"]
            ],
        }
        for mrec in by_mondai
    ]
    data = {
        "title": title,
        "subtitle": subtitle,
        "sideNavLabel": side_nav_label,
        "tabs": tabs,
    }
    if quiz_data is not None:
        data["quiz"] = quiz_data
    return data


def build_sections_html(sentences, questions, audio_rel, quiz_data=None):
    by_mondai = _group_by_mondai_question(sentences, questions)
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
            q_blocks.append(question_block_html(
                mi, qi, label,
                qrec["overview"], qrec["answer"],
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
    ap.add_argument("--data-driven", action="store_true", help="内容数据（每句原文token化"
                     "结果/翻译/笔记/填空/说话人）单独写进 <输出目录>/data.js，index.html "
                     "只是引用这份数据的壳（页面结构由 docs/js/page-renderer.js 在浏览器里"
                     "渲染出来）——想直接改内容（改翻译、改填空、订正读音）不用碰 HTML，"
                     "改 data.js 里对应字段就行。默认不传，保持跟以前完全一样的行为（内容"
                     "直接烘焙进 index.html），已发布页面不受影响，只有明确传了这个 flag "
                     "才走新路径")
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

    pwd_hash = args.password_hash or hashlib.sha256(args.password.encode("utf-8")).hexdigest()
    side_nav_label = html.escape(args.side_nav_label)
    toc_label_html = f'<div class="toc-label">{side_nav_label}</div>' if side_nav_label else ""

    if args.data_driven:
        lesson_data = build_lesson_data(
            args.title, args.subtitle, args.side_nav_label,
            sentences, questions, "audio/", quiz_data
        )
        out_data_js = os.path.join(args.out_dir, "data.js")
        # indent=2 让每个属性单独一行——这是给人改的文件，不是纯粹的传输格式，
        # 排版紧凑成一行虽然省字节但没人会想在一整行 JSON 里定位要改的字段。
        with open(out_data_js, "w", encoding="utf-8") as f:
            f.write("window.LESSON_DATA = ")
            json.dump(lesson_data, f, ensure_ascii=False, indent=2)
            f.write(";\n")

        page = SHELL_TEMPLATE.format(
            title=html.escape(args.title),
            subtitle=args.subtitle,
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
        print(f"Wrote {out_html}, {out_data_js} and {len(sentences)} audio clips to {audio_out_dir}")
        return

    sections, tab_buttons, side_nav_lists, side_nav_lists_mobile, mobile_nums_lists = \
        build_sections_html(sentences, questions, "audio/", quiz_data)

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
