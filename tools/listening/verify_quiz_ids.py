# -*- coding: utf-8 -*-
"""
用法：
  python verify_quiz_ids.py docs/private/<slug>/index.html [--fix]

単語テスト tab 的"听音频写假名"题型播放音频时，用的是 `quiz_data.json` 里
每个词条自己的 `id` 字段拼出 `audio/seg-{id:03d}.mp3`（见 `listening-page.js`
的 `audioSrcFor()`）——这个 `id` 必须跟"生词"tab 里同一个词自己的卡片音频用
的是同一个数字，否则播放的会是完全不相关的另一段音频（甚至是别的句子）。

真实案例（textbook-sjp-zg-l11）：这个页面全部 144 个生词条目的 `id` 都比
真实音频编号小了 35（35 正好是这一课"会话+课文"两个 tab 合起来的句子数）——
`vocab_words.json`（喂给 `build_vocab_quiz_data.py` 的词表）里的 `id` 字段
用的是"生词自己从1开始编号"，没有像"生词"tab 自己的生成流程那样加上前面
会话+课文占用的编号偏移，导致单词测试里几乎每一类涉及音频的题目播放的都是
错误内容，而且这个 bug **不会被之前任何一项自动化校验发现**——`verify_
clips.py` 检查的是每段音频文件本身内容对不对，这里音频文件本身完全没问题，
问题是"引用了哪个文件"这一层数据链接错了；`audit_furigana.py` 检查的是
读音，跟这个也无关。只有真的点开单词测试、听音频对比才会发现（用户就是这样
发现的），或者像这个脚本一样专门去比对"quiz_data 引用的 id"和"生词卡片
真实用的 id"是否一致。

**校验方法**：不依赖固定的偏移量猜测（不同课偏移量不一样，取决于这一课
会话+课文一共多少句），而是直接从已生成页面的"生词"tab 里按文档顺序抓出
每张卡片真实用的音频编号，跟 `quiz_data.json` 里按顺序排列的词条一一对应
比较——两边条目数必须完全一致（不一致说明词表本身就对不上，这个脚本会
报错而不是硬凑），顺序也必须一致（`quiz_data.json` 的词条顺序来自
`vocab_words.json` 的原始顺序，跟"生词"tab 卡片的生成顺序是同一份词表、
理应完全一致）。**不用按 text 精确匹配再查字典**——文字相同的词条可能不止
一个（比如同一课里"その後"出现了两次，读音还不一样），按文档顺序位置对应
比按文字比对更可靠，不会被重名词条搞乱。

默认只报告不对的地方，不改文件；加 `--fix` 才会把算出来的正确 id 写回
（data-driven 页面写回同目录 data.js 的 `quiz` 字段；旧式页面写回页面自己的
`<script id="vocab-quiz-data">`——`category`/`sentence`/`blank` 这些字段都
不受影响，只改 `id`）。**这一步应该跟 `verify_clips.py`/`audit_furigana.py`
一样，成为生成単語テスト tab 之后的必做校验**，不能假设"数据流水线走完了
就一定没问题"——这次的坑恰恰是流水线每一步单独看都没报错，只有连起来最终
交叉比对才能发现。

**data-driven 页面**（同目录有 `data.js`）：直接从 `window.LESSON_DATA.quiz`
读词条、从 `tabs[].sentences[]`（mondai 等于 --vocab-label 的那个 tab）按
文档顺序读真实 id，不用碰 HTML、也不用正则解析——`data.js` 是结构化数据，
sentence 的 `id` 字段本来就是"真实音频编号"，不需要像旧式 HTML 那样从
`<audio src="...">` 反推。
"""
import sys
import os
import re
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_page import normalize_numbers  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SECTION_RE = re.compile(r'<section class="mondai-section[^"]*"[^>]*>(.*?)</section>', re.S)
_H2_RE = re.compile(r"<h2>([^<]*)</h2>")
_AUDIO_RE = re.compile(r'<audio id="a(\d+)"[^>]*src="audio/seg-(\d+)\.mp3"')
_QUIZDATA_RE = re.compile(
    r'(<script type="application/json" id="vocab-quiz-data">)(.*?)(</script>)', re.S
)


def extract_vocab_real_ids_html(html, vocab_label):
    """旧式页面：按文档顺序返回"生词"tab 里每张卡片真实用的音频编号列表。"""
    for body in _SECTION_RE.findall(html):
        h2 = _H2_RE.search(body)
        if h2 and h2.group(1).strip() == vocab_label:
            return [int(seg) for _aid, seg in _AUDIO_RE.findall(body)]
    return None


def extract_vocab_real_ids_data(lesson_data, vocab_label):
    """data-driven 页面：按文档顺序返回"生词"tab 里每句真实的 id 列表。"""
    for tab in lesson_data.get("tabs", []):
        if tab.get("mondai") == vocab_label:
            return [s["id"] for q in tab["questions"] for s in q["sentences"]]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html_path")
    ap.add_argument("--fix", action="store_true", help="真的写回文件，不传就只打印报告")
    ap.add_argument("--vocab-label", default="生词", help="生词 tab 的标签文字，默认“生词”")
    args = ap.parse_args()

    data_js_path = os.path.join(os.path.dirname(args.html_path), "data.js")
    is_data_driven = os.path.exists(data_js_path)

    if is_data_driven:
        raw = open(data_js_path, encoding="utf-8").read()
        raw = raw[raw.index("{"): raw.rindex("}") + 1]
        lesson_data = json.loads(raw)
        quiz = lesson_data.get("quiz")
        if quiz is None:
            print('FAIL: data.js 里没有 "quiz" 字段，这个页面没有単語テスト tab')
            sys.exit(1)
        real_ids = extract_vocab_real_ids_data(lesson_data, args.vocab_label)
    else:
        html = open(args.html_path, encoding="utf-8").read()
        m = _QUIZDATA_RE.search(html)
        if not m:
            print('FAIL: 页面里没找到 <script id="vocab-quiz-data">，这个页面没有単語テスト tab')
            sys.exit(1)
        quiz = json.loads(m.group(2))
        real_ids = extract_vocab_real_ids_html(html, args.vocab_label)

    if real_ids is None:
        print(f"FAIL: 没找到标签为「{args.vocab_label}」的 tab，检查 --vocab-label 是否正确")
        sys.exit(1)

    if len(real_ids) != len(quiz):
        print(f"FAIL: 生词 tab 有 {len(real_ids)} 句，quiz_data 有 {len(quiz)} 条词条，"
              f"数量对不上，说明词表本身就不一致，不能简单按顺序对应，需要人工核查")
        sys.exit(1)

    mismatches = [
        (i, entry["text"], entry["id"], real_id)
        for i, (entry, real_id) in enumerate(zip(quiz, real_ids))
        if entry["id"] != real_id
    ]

    if not mismatches:
        print(f"OK: {args.html_path} 全部 {len(quiz)} 条词条的 id 都跟生词卡片真实音频编号一致")
        return

    offsets = sorted(set(r - q for _i, _t, q, r in mismatches))
    print(f"FOUND: {len(mismatches)}/{len(quiz)} 条词条的 id 跟真实音频编号对不上"
          f"（偏移量: {offsets}）")
    for i, text, qid, rid in mismatches[:10]:
        print(f"  #{i} {text!r}: quiz id={qid} 但真实音频编号={rid}")
    if len(mismatches) > 10:
        print(f"  ...还有 {len(mismatches) - 10} 条，省略")

    if not args.fix:
        print("(预览模式，没有写回文件；确认偏移量看起来合理后加 --fix 真正写入)")
        return

    for entry, real_id in zip(quiz, real_ids):
        entry["id"] = real_id

    if is_data_driven:
        with open(data_js_path, "w", encoding="utf-8") as f:
            f.write("window.LESSON_DATA = ")
            json.dump(normalize_numbers(lesson_data), f, ensure_ascii=False, indent=2)
            f.write(";\n")
        print(f"wrote back to {data_js_path}")
    else:
        new_json = json.dumps(quiz, ensure_ascii=False)
        new_html = html[: m.start()] + m.group(1) + new_json + m.group(3) + html[m.end():]
        open(args.html_path, "w", encoding="utf-8").write(new_html)
        print(f"wrote back to {args.html_path}")


if __name__ == "__main__":
    main()
