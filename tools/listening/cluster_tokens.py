# -*- coding: utf-8 -*-
"""
共享工具（`jp-textbook-lesson`/其它 listening 系 skill 都能用）：把 word-level
Whisper 转写（`WhisperModel.transcribe(..., word_timestamps=True)` 的输出）里
相邻、间隔很小的 token 合并成"词/复合词"级别的 cluster，再对整个 cluster 的
原文一次性跑 pykakasi 转平假名。

## 为什么需要这个（真实踩过的坑）

Whisper 的 word-level 输出经常把一个复合词拆成单字 token（比如"真実"拆成
"真"+"実"两个 token）。如果直接对每个单字 token 独立跑 `pykakasi`，pykakasi
对孤立单字通常猜的是训读/其它罕见读音，而不是这个字在复合词里该有的音读——
真实案例：`真`独立转换成`まこと`、`実`独立转换成`み`，拼起来是"まことみ"，
跟"真実"真正的读音"しんじつ"完全对不上。这会导致任何"按假名读音做内容对齐/
匹配"的逻辑（比如拿 Whisper 识别文本的假名去跟词表读音比对）在这类词上
失败或者算出错误的时间边界。

`真実`整体作为一个字符串喂给 pykakasi 就没有这个问题（`to_hiragana("真実")`
正确输出`しんじつ`）——pykakasi 的词典匹配需要看到完整的复合词上下文。

## 解法

利用"同一个词内部的相邻 token 间隔几乎是 0，不同词之间的间隔通常有真实停顿"
这个规律（人工朗读词表/句子时的自然特征），把间隔 <= `gap_thresh` 的相邻 token
合并成一个 cluster（时间戳取首尾 token 的 start/end，原文直接拼接），再对
拼接后的原文整体转换。

`gap_thresh` 默认 0.2 秒，这是在教材生词表音频上验证过的经验值（真实案例
`textbook-sjp-zg-l11`）——真正的词内部（同一个词的不同 mora）间隔几乎总是
0，不同词之间的停顿即使很短也很少低于 0.5 秒。如果某个音频源的停顿习惯不同
（比如语速很快的会话录音），可以调小这个阈值，但要留意别把"词内部罕见的
稍长间隔"（比如促音/长音前）也错误地当成词边界拆开了。

## 用法

    from cluster_tokens import load_and_cluster, to_hiragana

    clusters = load_and_cluster("wordlevel.txt", gap_thresh=0.2)
    # clusters: [(start, end, concatenated_original_text), ...]
    for start, end, text in clusters:
        reading = to_hiragana(text)  # 正确处理复合词音读

`wordlevel.txt` 格式：每行 `start\tend\ttoken`（tab 分隔），比如用这段代码
生成：

    segs, info = model.transcribe(audio, language="ja", word_timestamps=True, vad_filter=False)
    with open("wordlevel.txt", "w", encoding="utf-8") as f:
        for s in segs:
            for w in s.words:
                f.write(f"{w.start:.2f}\t{w.end:.2f}\t{w.word}\n")
"""
import re
import pykakasi

_kks = pykakasi.kakasi()
_PUNCT_RE = re.compile(r"[\s　、。，,．.!?！？「」『』()（）:：;；~〜・…\-—―'\"０-９0-9]")


def to_hiragana(text):
    text = _PUNCT_RE.sub("", text or "")
    return "".join(t["hira"] for t in _kks.convert(text))


def load_tokens(path):
    """读取 start\\tend\\ttoken 格式的 word-level 转写文件，按时间排序。"""
    raw = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 3:
                continue
            st, e, tok = parts
            raw.append((float(st), float(e), tok))
    raw.sort(key=lambda x: x[0])
    return raw


def cluster(raw_tokens, gap_thresh=0.2):
    """把已排序的 (start, end, text) 列表按间隔合并成 cluster。"""
    clusters = []
    cur = None
    for st, e, tok in raw_tokens:
        if cur is None:
            cur = [st, e, tok]
        elif st - cur[1] <= gap_thresh:
            cur[1] = e
            cur[2] += tok
        else:
            clusters.append(tuple(cur))
            cur = [st, e, tok]
    if cur is not None:
        clusters.append(tuple(cur))
    return clusters


def load_and_cluster(path, gap_thresh=0.2):
    return cluster(load_tokens(path), gap_thresh=gap_thresh)
