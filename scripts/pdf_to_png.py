#!/usr/bin/env python3
"""
pdf_to_png.py — 将 PDF 文件按页拆分为 PNG 图片

用法:
    python pdf_to_png.py <pdf_path> [output_dir] [--dpi 300]

说明:
    - 使用 PyMuPDF (fitz) 读取 PDF，每页输出一张 PNG 图片。
    - 输出文件命名: page_001.png, page_002.png, ...（三位数字补零）。
    - 默认输出目录: 与 PDF 同一目录下的 <pdf文件名>_pages/ 文件夹。
    - 可选 --dpi 参数控制输出分辨率，默认 300 DPI。
"""

import argparse
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="将 PDF 文件按页拆分为 PNG 图片",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python pdf_to_png.py exam.pdf\n"
            "  python pdf_to_png.py exam.pdf ./output --dpi 200\n"
        ),
    )
    parser.add_argument("pdf_path", type=str, help="输入的 PDF 文件路径")
    parser.add_argument(
        "output_dir",
        type=str,
        nargs="?",
        default=None,
        help="输出目录（默认: <pdf所在目录>/<pdf文件名>_pages/）",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="输出图片 DPI（默认: 300）",
    )
    return parser.parse_args()


def validate_pdf(pdf_path: str) -> Path:
    """验证 PDF 文件是否存在且可读"""
    path = Path(pdf_path)
    if not path.exists():
        print(f"错误: 文件不存在 — {pdf_path}", file=sys.stderr)
        sys.exit(1)
    if not path.is_file():
        print(f"错误: 路径不是文件 — {pdf_path}", file=sys.stderr)
        sys.exit(1)
    # 尝试打开以验证是否为有效 PDF
    try:
        import fitz
        doc = fitz.open(str(path))
        doc.close()
    except Exception as e:
        print(f"错误: 无法打开 PDF 文件 — {e}", file=sys.stderr)
        sys.exit(1)
    return path


def resolve_output_dir(pdf_path: Path, output_dir: str | None) -> Path:
    """确定输出目录，不存在则创建"""
    if output_dir:
        out = Path(output_dir)
    else:
        out = pdf_path.parent / f"{pdf_path.stem}_pages"
    out.mkdir(parents=True, exist_ok=True)
    return out


def pdf_to_png(pdf_path: Path, output_dir: Path, dpi: int) -> list[Path]:
    """
    将 PDF 每页导出为 PNG 图片。

    返回生成的 PNG 文件路径列表（按页码顺序）。
    """
    import fitz  # PyMuPDF

    doc = fitz.open(str(pdf_path))
    total = len(doc)
    digits = max(3, len(str(total)))  # 至少三位补零
    generated: list[Path] = []

    print(f"开始转换: {pdf_path.name}")
    print(f"总页数: {total}")
    print(f"DPI: {dpi}")
    print(f"输出目录: {output_dir}")
    print("-" * 40)

    for i, page in enumerate(doc, start=1):
        # 使用矩阵提高渲染分辨率
        zoom = dpi / 72.0  # PDF 默认 72 DPI
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        filename = f"page_{i:0{digits}d}.png"
        filepath = output_dir / filename
        pix.save(str(filepath))
        generated.append(filepath)

        print(f"  [{i:0{digits}d}/{total:0{digits}d}] {filename}  ({pix.width}x{pix.height})")

    doc.close()

    print("-" * 40)
    print(f"完成! 共生成 {len(generated)} 张图片，保存至: {output_dir}")
    return generated


def main() -> None:
    """主函数"""
    args = parse_args()
    pdf_path = validate_pdf(args.pdf_path)
    output_dir = resolve_output_dir(pdf_path, args.output_dir)
    pdf_to_png(pdf_path, output_dir, args.dpi)


if __name__ == "__main__":
    main()
