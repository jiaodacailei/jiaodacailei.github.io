# -*- coding: utf-8 -*-
"""
用法：
  python compute_clause_bounds.py <enriched_combined.json> <合并后的音频>
      [--search-back 0.4] [--search-front 0.4] [--frame-ms 5]
      [--min-rise 6] [--quiet-ceiling -38] [--margin 0.0]
      [--fix] [--report report.txt]

给会话/课文的每一句（有 char_times 的句子）按逗号（"，"）位置计算句内分句
边界（`clauseBounds`），供前端"选段复读"功能精确定位到小句起止时间——
`char_times`/`.tw[data-t]` 是跟读高亮用的，本来就容许 0.1~0.3 秒误差
（标点字符的时间戳还是插值猜的，不是真实测量），直接拿它当播放切割点会
出现"选中的小句和实际发音对不上"的问题，这个工具就是为了解决这个问题。

## 算法（复用 audit_boundaries_quietpoint.py 的 rms_window()，同一套思路）

对每个逗号所在字符下标 i：
1. `char_times[i+1]`（逗号后一个字符，也就是下一个小句开头字符）的时间戳
   给出一个粗略候选位置 `rough_t`——这个位置本身可能有 0.1~0.3 秒误差，
   不能直接用。
2. 在 `[rough_t-search_back, rough_t+search_front]` 这个窗口内找真正的
   响度最低点 `quiet_min`（响度剖面不依赖任何转写文本，直接测量比猜时间戳
   可靠，这个判据跟 audit_boundaries_quietpoint.py 同一个道理）。
3. 只有当 `quiet_min` 比候选位置本身明显更安静（`rise` 超过 `--min-rise`
   dB）、且 `quiet_min` 自己响度低于 `--quiet-ceiling`（真的接近安静，不是
   "说话中相对没那么响的一瞬间"）时，才认为这个逗号处存在真实停顿，取
   `quiet_min + margin` 作为这个分句边界。

**两个条件有一个不满足就跳过这个逗号，不勉强给出一个不可靠的边界**——比如
"赤か濃い紺色，灰色の…"这种快速列举，逗号处基本没有停顿，勉强给一个假边界
只会让"选段复读"切进相邻小句的内容里，比完全不切分更糟。这意味着
`clauseBounds` 里的分句点数量可能比这句原文里的逗号数量少，这是设计如此，
不是 bug。

只处理"，"（全角逗号）——这批教材统一用这个标点分句，"、"（顿号）目前没在
分句语义上出现过，真遇到再加。

## 运行位置

在 `merge_sections.py` 之后跑（在合并后的 `enriched_combined.json` +
合并音频上直接计算），不需要再处理"这段在合并音频里的偏移量"——用哪个
坐标系跟 `char_times`/`start`/`end` 完全一致。默认只打印报告，`--fix` 才
真正把结果写回 `clauseBounds` 字段（数组，绝对时间，跟 `start`/`end`
一个坐标系）。
"""
import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_boundaries_quietpoint import rms_window

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CLAUSE_PUNCT = "，"


def find_clause_bounds_for_sentence(audio_path, s, args):
    text = s["text"]
    char_times = s.get("char_times")
    if not char_times or len(char_times) != len(text):
        return [], []

    bounds = []
    skipped = []
    for i, ch in enumerate(text):
        if ch not in CLAUSE_PUNCT:
            continue
        if i + 1 >= len(char_times):
            continue
        rough_t = char_times[i + 1]
        lo = max(rough_t - args.search_back, s["start"] + 0.05)
        hi = min(rough_t + args.search_front, s["end"] - 0.05)
        if hi <= lo:
            skipped.append((i, rough_t, "窗口越界"))
            continue

        vals = rms_window(audio_path, lo - 0.05, (hi - lo) + 0.1, args.frame_ms)
        if not vals:
            skipped.append((i, rough_t, "取不到响度数据"))
            continue
        window_vals = [(t, db) for t, db in vals if lo <= t <= hi]
        if not window_vals:
            skipped.append((i, rough_t, "窗口内无数据"))
            continue
        min_t, min_db = min(window_vals, key=lambda x: x[1])
        # 参照点用窗口内最响的位置（说话声音本身），不能用 rough_t 自己的响度——
        # rough_t 只是一个可能有 0.1~0.3 秒误差的插值猜测，如果它本来就已经蒙对、
        # 落在真实安静点附近，跟它自己比 rise 会算出接近 0，被误判成"没找到停顿"，
        # 但其实这正是最理想的情况（候选位置本来就准）。用窗口内的响度峰值当参照，
        # 判断的是"这个窗口里有没有从说话声音到安静的真实落差"，不受 rough_t
        # 具体落在窗口哪个位置影响。
        loud_in_window = max(db for _, db in window_vals)
        rise = round(loud_in_window - min_db, 1)

        if rise < args.min_rise or min_db > args.quiet_ceiling:
            skipped.append((i, rough_t, f"未找到确信停顿 rise={rise} min_db={min_db}"))
            continue

        bounds.append(round(min_t + args.margin, 2))

    return bounds, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("enriched_json")
    ap.add_argument("audio")
    ap.add_argument("--frame-ms", type=int, default=5)
    ap.add_argument("--search-back", type=float, default=0.4)
    ap.add_argument("--search-front", type=float, default=0.4)
    ap.add_argument("--min-rise", type=float, default=6.0,
                     help="quiet_min 比候选位置响度低出这个值（dB）才算找到真实停顿")
    ap.add_argument("--quiet-ceiling", type=float, default=-38.0,
                     help="quiet_min 自己的响度必须低于这个值（dB）才算真的安静")
    ap.add_argument("--margin", type=float, default=0.0)
    ap.add_argument("--fix", action="store_true", help="把结果写回 enriched_json 的 clauseBounds 字段")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    data = json.load(open(args.enriched_json, encoding="utf-8"))
    sentences = data["sentences"]

    lines = []
    total_commas = 0
    total_bounds = 0
    for s in sentences:
        if not s.get("char_times"):
            continue
        commas = s["text"].count(CLAUSE_PUNCT)
        if commas == 0:
            continue
        bounds, skipped = find_clause_bounds_for_sentence(args.audio, s, args)
        total_commas += commas
        total_bounds += len(bounds)
        lines.append(f'{s["id"]:4d} {s["text"][:30]:30s} 逗号{commas}处 -> clauseBounds={bounds}')
        for i, rough_t, reason in skipped:
            lines.append(f'         跳过第{i}处逗号 (rough_t={rough_t:.2f}): {reason}')
        if args.fix:
            s["clauseBounds"] = bounds

    summary = f"共{len(sentences)}句，{total_commas}处逗号，找到{total_bounds}处确信分句边界"
    out = "\n".join(lines) + "\n\n" + summary + "\n"
    if args.report:
        open(args.report, "w", encoding="utf-8").write(out)
        print(f"报告写入 {args.report}；{summary}")
    else:
        print(out)

    if args.fix:
        json.dump(data, open(args.enriched_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"--fix：已写回 {args.enriched_json}")


if __name__ == "__main__":
    main()
