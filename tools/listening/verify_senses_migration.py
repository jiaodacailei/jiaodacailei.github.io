import json
import subprocess
import sys

sys.path.insert(0, ".")

# 原始（迁移前）overview 直接从 git HEAD 读，不依赖本地缓存的快照文件。
old_source = subprocess.run(
    ["git", "show", "HEAD:tools/listening/n2_vocab_content.py"],
    cwd="..\\..", capture_output=True, text=True, encoding="utf-8",
).stdout
old_ns = {}
exec(compile(old_source, "n2_vocab_content_old.py", "exec"), old_ns)
OLD_UNITS = old_ns["UNITS"]

sys.path.insert(0, ".")
import importlib
import build_n2_reference_page as bnrp
importlib.reload(bnrp)
from build_n2_reference_page import quiz_zh_text, derive_meaning_variants

before = []
for u in OLD_UNITS:
    for p in u["points"]:
        overview = p.get("overview", "")
        before.append({
            "title": p["title"],
            "overview": overview,
            "zh": quiz_zh_text(p),
            "zhVariants": derive_meaning_variants(p),
        })

units, _ = bnrp.load_content("n2_vocab_content.py")
after = []
for u in units:
    for p in u["points"]:
        after.append({
            "title": p["title"],
            "overview": p.get("overview", ""),
            "zh": quiz_zh_text(p),
            "zhVariants": derive_meaning_variants(p),
        })

assert len(before) == len(after), (len(before), len(after))

mismatches = []
for b, a in zip(before, after):
    assert b["title"] == a["title"], (b["title"], a["title"])
    if b["overview"] != a["overview"] or b["zh"] != a["zh"] or b["zhVariants"] != a["zhVariants"]:
        mismatches.append((b, a))

print(f"total: {len(after)}, mismatches: {len(mismatches)}")
for b, a in mismatches:
    print("----", b["title"])
    if b["overview"] != a["overview"]:
        print("  overview before:", repr(b["overview"]))
        print("  overview after :", repr(a["overview"]))
