# -*- coding: utf-8 -*-
"""正式迁移脚本（会改写 n2_vocab_content.py）：把每个词条的
`"overview": "...",` 这一行替换成 `"senses": [...],` (+ 可选的
`"annotations": "...",`)。

前提（已用 migrate_vocab_senses.py 的分析模式验证过）：
- 全部900个 overview 字段都是单行字符串字面量，缩进固定16个空格，
  行尾固定是 `",`，可以整行做文本级替换，不需要碰 AST。
- parse_overview() 解析出的 senses 反拼回去（配合原样保留的注释行）跟
  原始 overview 逐字一致（唯一允许的例外是"[词性]"后有没有空格、
  顿号/逗号混用这两种排版风格，这两种差异不影响任何字段的实际内容）。

annotations 字段存的是"最后一个义项行之后的原始文本"，逐字保留，不做
任何解析/改写——这次迁移只把"释义"这部分变成结构化数据，类义词/关联词
这类注释暂时还是自由文本（跟 related 结构化字段并存），见设计文档
《N2词汇overview结构化-设计文档.md》"前端JS：这次不动（留作可选二期）"
一节，related 字段进一步结构化留到下一阶段。
"""
import ast
import json
import re

from migrate_vocab_senses import parse_overview

OVERVIEW_LINE_RE = re.compile(r'^                "overview": (".*"),$')


def process_file(path):
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    out = []
    changed = 0
    for line in lines:
        m = OVERVIEW_LINE_RE.match(line.rstrip("\n"))
        if not m:
            out.append(line)
            continue
        overview = ast.literal_eval(m.group(1))
        senses, annotation_lines = parse_overview(overview)
        senses_json = json.dumps(senses, ensure_ascii=False)
        out.append(f'                "senses": {senses_json},\n')
        ann_text = "\n".join(annotation_lines)
        if ann_text:
            ann_json = json.dumps(ann_text, ensure_ascii=False)
            out.append(f'                "annotations": {ann_json},\n')
        changed += 1

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)
    print(f"{path}: replaced {changed} overview lines")


if __name__ == "__main__":
    process_file("n2_vocab_content.py")
