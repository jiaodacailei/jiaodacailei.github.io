# -*- coding: utf-8 -*-
"""
用法：python render_pdf_pages.py <PDF文件> <输出目录> [--pages 25-31] [--dpi 200]

把 PDF 逐页渲染成 PNG 图片，供 Claude 用 Read 工具直接"看"页面内容做人工核对——
不是转写文本。用在 JLPT 真题这类场景：网上流传的"真题解析"PDF 经常是盗版/扫描件
重新排版出来的，**内嵌字体的 ToUnicode 映射表是坏的**（字形显示正常，但复制粘贴/
文本提取拿到的是乱码），`pdftotext`、`PyPDF2`、`pdfplumber`、PyMuPDF 的
`page.get_text()` 这类基于文本层提取的工具在这类 PDF 上全部失效，唯一可靠的办法是
按像素渲染成图片再人工读——渲染是走字体的字形轮廓画图，不经过 ToUnicode 映射，不
受这个问题影响。

这台机器上系统没装 poppler（`pdftoppm`），Read 工具自带的 PDF 页面渲染、
`pdf2image` 这类依赖 poppler 的方案都用不了；这个脚本改用纯 Python 的 PyMuPDF
（`pip install pymupdf`，不依赖系统装 poppler/ghostscript）做渲染，装一次就行。

`--pages` 不传就渲染全部页（页数多、真题 PDF 常有 30+ 页，建议先只渲染目标页码
范围，比如已经用 `find_item_boundaries.py`/转写文本大致定位到"問題5 在录音接近
结尾的位置"，PDF 里大概率也在接近末尾的页码，没必要整份渲染）。页码从1开始，
支持单页/范围/逗号分隔混合，如 "1,3,25-31"。

输出文件名 `page{N:03d}.png`（N 是1-based页码），渲染完打印每张图的完整路径，
方便直接喂给 Read 工具逐张看。
"""

import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def parse_pages(spec, total):
    if not spec:
        return list(range(1, total + 1))
    result = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            result.extend(range(int(a), int(b) + 1))
        else:
            result.append(int(part))
    bad = [p for p in result if p < 1 or p > total]
    if bad:
        raise SystemExit(f"页码超出范围（PDF 共 {total} 页）：{bad}")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out_dir")
    ap.add_argument("--pages", default=None, help='如 "1,3,25-31"，不传则渲染全部页')
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()

    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise SystemExit(
            "缺少 PyMuPDF，先装：python -m pip install --user pymupdf"
        )

    doc = fitz.open(args.pdf)
    pages = parse_pages(args.pages, doc.page_count)
    os.makedirs(args.out_dir, exist_ok=True)

    for p in pages:
        page = doc[p - 1]
        pix = page.get_pixmap(dpi=args.dpi)
        out_path = os.path.join(args.out_dir, f"page{p:03d}.png")
        pix.save(out_path)
        print(out_path)


if __name__ == "__main__":
    main()
