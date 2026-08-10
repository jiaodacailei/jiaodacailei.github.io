# -*- coding: utf-8 -*-
"""
用法：
  python apply_manual_overrides.py <enriched.json> <manual_overrides.json> <输出.json>

共享工具（`jp-textbook-lesson` 用）：把人工用 RMS/word-level 核实过的边界
订正值，从"改完这一次就完事"升级成"每次重新跑 refine_boundaries.py 之后
都自动重新生效"——直接解决 textbook-sjp-zg-l14 这一课踩过的最大一次真实
坑：`refine_boundaries.py` 每次都是从头对整个题目分组重新对齐，完全不知道
"这个位置之前人工核实过、有个更可信的手动订正值"这回事，之前只能靠人记得
"这次因为别的原因（合并/拆分句子）要重新走一遍对齐，得把所有手动订正过的
边界都回去重新核对一遍"——真实案例：会话里两处已经用 RMS 核实修复过的
边界（`王さん`开头/`これ`开头），因为后来要合并"ええ"/"いいえ"这两句、
触发了一次全新的 `refine_boundaries.py`，在没人记得要重新核对的情况下被
静默覆盖回了原来的错误值，直到下一轮用户反馈才发现。

## 用法

`manual_overrides.json` 格式：
```json
{
  "これ，つまらないものですが……。": {"start": 21.60, "char_time_first": 21.65},
  "あれ，そんなに気を使わなくてよかったのに。": {"end": 27.44, "char_time_last": 27.44}
}
```
**按句子的 `text` 字段原文精确匹配**（不是按 `id`——`id` 会在每次
resplit/合并之后重新编号，`text` 只要这句话本身没有被拆分/合并/改写就
不会变，才是跨多轮重新生成依然稳定的锚点）。每条订正可以只给
`start`/`end` 其中一个、两个都给，或者额外再给 `char_time_first`/
`char_time_last`——`start`/`end` 决定音频真正切在哪（避免内容丢失，
最要紧的一项），`char_time_first`/`char_time_last` 决定跟读高亮第一个/
最后一个字符具体几点几秒亮起（不给的话只会做"越界就夹回边界内"这种
保底处理，不会主动改成你之前手工核实过的精确值——精度不如显式指定，
但不会导致高亮指向音频范围外）。真正核实过精确起音/收音时间点的场景
建议把这两个字段也一起写上，不要只写 `start`/`end`。

**每次改完一批边界、确认是真实bug并且用 RMS/word-level 核实过正确值之后，
随手把这条订正记进这一课工作目录下的 `manual_overrides.json`（不存在就新建），
再跑一遍本脚本重新生成 `enriched_*_final.json` 覆盖掉刚才手工 patch 的结果**
——这样即使后续因为别的原因（比如这一课又要合并/拆分句子）要重新跑一遍
`refine_boundaries.py`，也只需要在 `validate_boundaries.py` 之后再跑一遍本
脚本，之前核实过的订正会自动重新生效，不用凭记忆一条条回去重新核对。

覆盖之后同步重算这句自己的 `char_times`——只是把越界的首/尾字符时间戳夹
（clamp）到新的边界内，不是重新跑一遍完整对齐（对齐算法本身没有问题，
问题只出在边界数值被覆盖导致 char_times 跟新边界不匹配这一点）。
"""
import sys
import json
import argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("enriched_json")
    ap.add_argument("overrides_json")
    ap.add_argument("out_json")
    args = ap.parse_args()

    data = json.load(open(args.enriched_json, encoding="utf-8"))
    overrides = json.load(open(args.overrides_json, encoding="utf-8"))

    by_text = {}
    for s in data["sentences"]:
        by_text.setdefault(s["text"], []).append(s)

    applied, missing = [], []
    for text, ov in overrides.items():
        matches = by_text.get(text)
        if not matches:
            missing.append(text)
            continue
        for s in matches:
            if "start" in ov:
                s["start"] = ov["start"]
            if "end" in ov:
                s["end"] = ov["end"]
            if s.get("char_times"):
                ct = s["char_times"]
                # 显式给了精确值就直接用（之前人工用 RMS/word-level 核实过的
                # 真实起音/收音时刻，比"只做越界保底"精确），没给才退回 clamp。
                if "char_time_first" in ov:
                    ct[0] = ov["char_time_first"]
                elif ct[0] < s["start"]:
                    ct[0] = s["start"]
                if "char_time_last" in ov:
                    ct[-1] = ov["char_time_last"]
                elif ct[-1] > s["end"]:
                    ct[-1] = s["end"]
                # 保证仍然单调不减，clamp/显式赋值都可能把首/尾挤到比相邻
                # 字符更靠后/靠前
                for i in range(1, len(ct)):
                    if ct[i] < ct[i - 1]:
                        ct[i] = ct[i - 1]
                for i in range(len(ct) - 2, -1, -1):
                    if ct[i] > ct[i + 1]:
                        ct[i] = ct[i + 1]
            applied.append((s["id"], text[:20]))

    json.dump(data, open(args.out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"applied {len(applied)} override(s):")
    for sid, snippet in applied:
        print(f"  id={sid} {snippet!r}")
    if missing:
        print(f"WARNING: {len(missing)} override(s) in {args.overrides_json} 没有在 "
              f"{args.enriched_json} 里找到匹配的句子（原文改过/被合并拆分过？需要人工确认这条"
              f"订正是不是已经不适用了，不要默默丢弃）:")
        for text in missing:
            print(f"  {text!r}")


if __name__ == "__main__":
    main()
