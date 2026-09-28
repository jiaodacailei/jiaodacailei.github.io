# -*- coding: utf-8 -*-
"""一次性迁移分析脚本（不改写数据）：把 n2_vocab_content.py 里每个词条的
`overview` 第一部分（释义）解析成设计文档《N2词汇overview结构化-设计文档.md》
里定义的 `senses` 结构（[{pos, groups:[[phrase,...],...]}, ...]），然后：
1. 把解析结果重新拼回文本，跟原始 overview 的"释义部分"逐字比对——不一致
   的进"round-trip不一致"清单，需要人工核对原书截图。
2. 对每个词条的 senses 做"同一个 sense 内跨 group 短语碰撞"检测（子串或
   完全相同都算）——命中的进"跨组碰撞"清单，这是这次要修的"短语泄漏"
   问题的数据层面根因，也需要人工核对原书截图确认是不是分号分组本身
   切错了。

跑法：`python migrate_vocab_senses.py [unit_index]`，不传参数就跑全部单元。
只读不写，方便反复跑、反复调整解析规则，等规则稳定、清单收敛到人工能过
一遍的规模，再写正式的"落盘迁移"脚本。
"""
import re
import sys

sys.path.insert(0, ".")
from n2_vocab_content import UNITS  # noqa: E402

POS_LINE_RE = re.compile(r"^\s*[\[［]([^\]］]*)[\]］]\s*(.*)$")

_BRACKET_OPEN = set("（(「『")
_BRACKET_CLOSE = set("）)」』")


def smart_split(text, delims):
    """按 delims 里的字符切分 text，但跳过括号（全半角圆括号/「」/『』）
    内部——书上不少释义会在括号里用顿号列举好几样东西（比如"（地位、
    价格等）提高"），这个顿号是括号内部的一个列表，不是"这一整段释义"
    跟后面的近义说法之间的分隔符。早期版本不分场合见顿号/逗号就切，
    切出"（地位"/"价格等）提高"这种残缺括号片段——拼回展示文本时靠
    "重新用逗号连接"侥幸掩盖了这个问题（两边render出来的字符串碰巧一样），
    但`senses.groups`数组里每个元素本该是一个完整、独立的近义说法，
    存进去半个括号明显是错的，所以在切分这一步就要跳过括号深度>0的
    位置，不能事后再打补丁。"""
    parts = []
    buf = []
    depth = 0
    for ch in text:
        if ch in _BRACKET_OPEN:
            depth += 1
            buf.append(ch)
        elif ch in _BRACKET_CLOSE:
            depth = max(0, depth - 1)
            buf.append(ch)
        elif depth == 0 and ch in delims:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def parse_overview(overview):
    """返回 (senses, annotation_lines)。
    senses: [{"pos": str, "groups": [[str,...],...]}]
    annotation_lines: 跟在最后一个"义项行"后面的原始行（类义词/关联词等）。
    """
    lines = [l for l in (overview or "").split("\n")]
    senses = []
    last_pos_line_idx = -1
    for i, line in enumerate(lines):
        m = POS_LINE_RE.match(line)
        if not m:
            continue
        pos, rest = m.group(1), m.group(2)
        groups = [
            [p.strip() for p in smart_split(g, "，,、") if p.strip()]
            for g in smart_split(rest, "；;")
        ]
        groups = [g for g in groups if g]
        senses.append({"pos": pos, "groups": groups})
        last_pos_line_idx = i
    annotation_lines = lines[last_pos_line_idx + 1:] if last_pos_line_idx >= 0 else lines
    return senses, annotation_lines


def render_sense_line(sense):
    body = "；".join("，".join(g) for g in sense["groups"])
    return f"[{sense['pos']}] {body}"


def strip_punct(s):
    return re.sub(r"[\s、。，,．.!?！？「」『』()（）:：;；~〜・…\-—―'\"／/]", "", s)


def cosmetic_normalize(s):
    """判断 round-trip 差异是不是"无关内容"的排版风格（[词性]后有没有空格、
    顿号/逗号混用）——这两类都是转录者自己写中文释义时的排版随意性，不是
    书上日文原文的一部分，跟"是否忠于原书"无关，允许迁移时统一收敛成
    一种写法，不用逐条去核对照片。"""
    s = re.sub(r"([\]］])\s*", r"\1 ", s)
    s = s.replace("、", "，")
    return s


def find_cross_group_collisions(senses):
    """同一个 sense 内，任意两个不同 group 之间，如果一个 group 的某个短语
    是另一个 group 某个短语的子串（含完全相等），就算一次碰撞——这正是
    `checkJa2ZhMulti()` 判分时会出现"漏答也算对"的数据条件。"""
    hits = []
    for sense in senses:
        groups = sense["groups"]
        for i in range(len(groups)):
            for j in range(len(groups)):
                if i == j:
                    continue
                for pi in groups[i]:
                    spi = strip_punct(pi)
                    if not spi:
                        continue
                    for pj in groups[j]:
                        spj = strip_punct(pj)
                        if spj and spi in spj:
                            hits.append((sense["pos"], i, pi, j, pj))
    return hits


def analyze_unit(unit_idx):
    unit = UNITS[unit_idx]
    label = unit.get("label", f"单元{unit_idx}")
    roundtrip_mismatch = []
    cosmetic_only = 0
    collisions = []
    multi_group_count = 0
    for point in unit["points"]:
        title = point["title"]
        overview = point.get("overview", "")
        senses, annotation_lines = parse_overview(overview)
        if not senses:
            roundtrip_mismatch.append((title, "<没解析出任何义项行>", overview))
            continue
        rebuilt = "\n".join([render_sense_line(s) for s in senses] + annotation_lines)
        if rebuilt != overview:
            if cosmetic_normalize(rebuilt) == cosmetic_normalize(overview):
                cosmetic_only += 1
            else:
                roundtrip_mismatch.append((title, rebuilt, overview))
        if any(len(s["groups"]) > 1 for s in senses):
            multi_group_count += 1
        hits = find_cross_group_collisions(senses)
        if hits:
            collisions.append((title, hits))
    return label, len(unit["points"]), multi_group_count, cosmetic_only, roundtrip_mismatch, collisions


def main():
    targets = [int(sys.argv[1])] if len(sys.argv) > 1 else range(len(UNITS))
    for idx in targets:
        label, total, multi_group_count, cosmetic_only, roundtrip_mismatch, collisions = analyze_unit(idx)
        print(f"=== {label}（第{idx}项，共{total}词，多组义项{multi_group_count}条）===")
        print(f"排版风格差异（[词性]后空格/顿号逗号混用，可自动统一，不用核对照片）：{cosmetic_only} 条")
        print(f"round-trip不一致（需要核对照片）：{len(roundtrip_mismatch)} 条")
        for title, rebuilt, original in roundtrip_mismatch:
            print(f"  [MISMATCH] {title}")
            print(f"    原文: {original!r}")
            print(f"    重建: {rebuilt!r}")
        print(f"跨组短语碰撞：{len(collisions)} 条")
        for title, hits in collisions:
            print(f"  [COLLIDE] {title}")
            for pos, i, pi, j, pj in hits:
                print(f"    [{pos}] group{i}:{pi!r} 是 group{j}:{pj!r} 的子串")
        print()


if __name__ == "__main__":
    main()
