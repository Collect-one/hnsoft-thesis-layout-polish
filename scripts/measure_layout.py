#!/usr/bin/env python3
"""Report likely page-tail whitespace in a rendered thesis PDF.

This is a heuristic review aid, not a substitute for page-by-page visual
inspection. It ignores the running header and the bottom page number, then
measures the vertical distance from the last visible body block to the body
text boundary.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

try:
    import pymupdf
except ImportError as exc:  # pragma: no cover - exercised by users without PyMuPDF
    raise SystemExit("需要安装 PyMuPDF: python -m pip install pymupdf") from exc


def _line_text(line: dict[str, Any]) -> str:
    return "".join(span.get("text", "") for span in line.get("spans", [])).strip()


def analyze_page(page: Any, line_pt: float) -> dict[str, Any]:
    height = float(page.rect.height)
    text_lines: list[tuple[float, float, str]] = []
    image_blocks: list[tuple[float, float]] = []

    for block in page.get_text("dict").get("blocks", []):
        btype = block.get("type")
        if btype == 0:
            for line in block.get("lines", []):
                text = _line_text(line)
                if not text:
                    continue
                y0, y1 = float(line["bbox"][1]), float(line["bbox"][3])
                text_lines.append((y0, y1, text))
        elif btype == 1:
            y0, y1 = float(block["bbox"][1]), float(block["bbox"][3])
            image_blocks.append((y0, y1))

    text_lines.sort(key=lambda item: item[0])
    # The page number is normally the lowest text line. Its top edge gives a
    # more stable body boundary than assuming one fixed A4 margin.
    footer_candidates = [line for line in text_lines if line[1] > height - 65]
    footer_y = min((line[0] for line in footer_candidates), default=None)
    body_bottom = (footer_y - 10.0) if footer_y is not None else (height - 72.0)

    body_lines = [
        item for item in text_lines
        if item[0] > 65 and item[1] < body_bottom - 3
    ]
    body_images = [
        item for item in image_blocks
        if item[0] > 65 and item[1] < body_bottom - 3
    ]

    bottoms = [item[1] for item in body_lines]
    bottoms.extend(item[1] for item in body_images)
    content_bottom = max(bottoms, default=0.0)
    gap_pt = max(0.0, body_bottom - content_bottom)
    blank_lines = math.floor(gap_pt / line_pt)

    first = body_lines[0][2][:60] if body_lines else ""
    last = body_lines[-1][2][:60] if body_lines else ""
    return {
        "height_pt": round(height, 1),
        "body_bottom_pt": round(body_bottom, 1),
        "content_bottom_pt": round(content_bottom, 1),
        "gap_pt": round(gap_pt, 1),
        "blank_lines_est": blank_lines,
        "first_text": first,
        "last_text": last,
        "has_image": bool(body_images),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure page-tail whitespace in a PDF.")
    parser.add_argument("--pdf", required=True, help="Path to the rendered PDF")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--line-pt", type=float, default=22.0, help="Body line height in points")
    parser.add_argument("--threshold-lines", type=int, default=2, help="Report pages above this estimated blank-line count")
    parser.add_argument("--start-page", type=int, default=1, help="1-based PDF page where the body starts (often the page whose footer is 1)")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf_path)
    all_pages = [analyze_page(page, args.line_pt) for page in doc]
    if not 1 <= args.start_page <= len(all_pages):
        raise SystemExit(f"--start-page must be between 1 and {len(all_pages)}")
    pages = [
        {"pdf_page": i + 1, **data}
        for i, data in enumerate(all_pages)
        if i + 1 >= args.start_page
    ]
    flagged = [p for p in pages if p["blank_lines_est"] > args.threshold_lines]

    report = {
        "pdf": str(pdf_path),
        "page_count": len(all_pages),
        "body_start_pdf_page": args.start_page,
        "analyzed_page_count": len(pages),
        "line_pt": args.line_pt,
        "threshold_lines": args.threshold_lines,
        "flagged_pages": flagged,
        "pages": pages,
    }
    (out_dir / "layout_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 版面空白检查",
        "",
        f"- PDF：`{pdf_path}`",
        f"- PDF总页数：{len(all_pages)}",
        f"- 正文分析起始PDF页：{args.start_page}",
        f"- 估算行高：{args.line_pt} 磅",
        f"- 报告阈值：超过 {args.threshold_lines} 行",
        "",
        "## 需要目检的页面",
        "",
        "| PDF页 | 估算空白行 | 图片 | 页尾文字 |",
        "|---:|---:|:---:|---|",
    ]
    if flagged:
        for item in flagged:
            lines.append(
                f"| {item['pdf_page']} | {item['blank_lines_est']} | "
                f"{'是' if item['has_image'] else '否'} | {item['last_text']} |"
            )
    else:
        lines.append("| - | - | - | 未发现超过阈值的页尾空白 |")

    lines.extend(
        [
            "",
            "## 注意",
            "",
            "- 章末页允许较大空白，报告中的页面需要结合章节边界判断。",
            "- 页脚页码不计入正文空白；表格底线与图片边缘会使估算有少量误差。",
            "- 这是一项启发式测量，最终必须逐页查看 PNG/PDF。",
        ]
    )
    (out_dir / "layout_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Layout report written: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
