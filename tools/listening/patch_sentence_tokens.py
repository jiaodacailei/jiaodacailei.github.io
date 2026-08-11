# -*- coding: utf-8 -*-
"""
用法：
  python patch_sentence_tokens.py <docs/private/<slug>/data.js> <enriched_combined.json> <id1> [<id2> ...]

共享工具（`jp-textbook-lesson` 用）：改完某几句的边界（手工 patch 或
`apply_manual_overrides.py`）之后，把 `--data-driven` 页面的 `data.js` 里对应
句子的 `tokens`（跟读高亮用，每个字/词自己的绝对时间戳）跟着重新算一遍、
原地覆盖——`data.js` 里的 `tokens` 不会因为 `enriched_combined.json` 改了就
自动更新，两边是各自独立的静态数据，边界改完不补这一步的话页面上看到的
高亮时间戳还是旧的。

真实案例（textbook-sjp-zg-l14）：这一课改边界改了十几轮，每一轮都要手写一个
一次性小脚本（`patch_data_js.py`/`patch_data_js2.py`）重复同样的"读 enriched_
combined.json 里这几个 id 的 char_times、算 rel_char_times、调 tokenize_ja()、
按 id 找到 data.js 里对应位置覆盖"这套逻辑，只是每次改的 id 集合不一样——
抽成这一个通用工具，之后改哪几句直接把 id 当命令行参数传，不用现写。

只更新 `tokens`/`audio` 两个字段（`audio` 字段名固定跟着 id 走，`seg-{id:03d}.
mp3`，边界改了不代表文件名变，但保持跟 `sentence_to_data()`
生成时完全一致的写法，避免手滑打错），不动这句的 `zh`/`notes`/`blanks`/
`speaker` 等内容字段。**只负责 `data.js` 这一份文本数据，不切音频文件**——
音频文件本身要跟着改的话另外跑 `recut_clips.py`，两者互不依赖、顺序不影响
结果，但通常是先切音频、再补这一步。

会在 `data.js` 的所有 tab（不管是"会话""课文""生词"还是别的名字）里搜索匹配
`id` 的句子，不需要预先知道这个 id 属于哪个 tab。

跟 `build_lesson_data()` 一样，会先用整份 `enriched_combined.json` 构造
"生词表读音映射"传给 `tokenize_ja()`（见该函数文档字符串）——如果被 patch
的句子里有词跟生词表重名，直接复用生词表已经人工核实过的读音，不会退回
pykakasi 的自动猜测，保证跟真实页面渲染逻辑一致。
"""
import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_page import tokenize_ja  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_js")
    ap.add_argument("enriched_combined_json")
    ap.add_argument("ids", nargs="+", type=int)
    args = ap.parse_args()

    enriched = json.load(open(args.enriched_combined_json, encoding="utf-8"))
    by_id = {s["id"]: s for s in enriched["sentences"] if s["id"] in set(args.ids)}
    # 跟 build_lesson_data() 的构造方式完全一致——会话/课文句子里如果有词
    # 跟生词表重名，直接用生词表已经人工核实过的读音，见 tokenize_ja() 的
    # vocab_readings 参数文档。用完整 enriched["sentences"]（不是只看
    # by_id 这几条）构造，因为要复用的生词读音不一定就是这次改的这几个id。
    vocab_readings = {
        s["text"]: s["kana"]
        for s in enriched["sentences"]
        if not s.get("char_times") and s.get("kana")
    }

    missing = [i for i in args.ids if i not in by_id]
    if missing:
        print(f"FAIL: enriched_combined.json 里找不到这些 id: {missing}")
        sys.exit(1)

    raw = open(args.data_js, encoding="utf-8").read()
    start, end = raw.index("{"), raw.rindex("}") + 1
    prefix, body, suffix = raw[:start], raw[start:end], raw[end:]
    data = json.loads(body)

    patched = []
    for tab in data["tabs"]:
        for q in tab["questions"]:
            for s in q["sentences"]:
                if s["id"] in by_id:
                    es = by_id[s["id"]]
                    char_times = es.get("char_times")
                    if char_times:
                        rel_char_times = [round(t - es["start"], 2) for t in char_times]
                        s["tokens"] = tokenize_ja(es["text"], rel_char_times, vocab_readings)
                    else:
                        s["tokens"] = tokenize_ja(es["text"], vocab_readings=vocab_readings)
                    s["audio"] = f"audio/seg-{es['id']:03d}.mp3"
                    patched.append(s["id"])

    still_missing = set(args.ids) - set(patched)
    if still_missing:
        print(f"WARNING: 这些 id 在 data.js 的任何 tab 里都没找到，没有被更新: "
              f"{sorted(still_missing)}（是不是传错了 data.js，或者这个 id 只存在于"
              f"enriched_combined.json 但从没生成进页面？）")

    with open(args.data_js, "w", encoding="utf-8") as f:
        f.write(prefix)
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write(suffix)

    print("patched sentence ids:", sorted(patched))


if __name__ == "__main__":
    main()
