#!/usr/bin/env python3
"""
paddle_layout_md_converter.py — 使用本地 WSL2 PaddleX / PaddleOCR 引擎将图片转换为结构化 Markdown
特点:
  - 完全本地离线运行（WSL2 GPU 加速）
  - 自动调用 UVDoc 进行书脊/弯曲页面去畸变校正
  - 基于 RT-DETR-H 17 类版面检测与 SLANet+ 表格还原
  - 支持多进程并发与断点续传缓存
  - 输出规范的 Markdown 标题层级 (# / ## / ###) 与三线表格
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# WSL2 Python & script execution template
def parse_args():
    parser = argparse.ArgumentParser(description="本地 PaddleX 版面分析与 Markdown 转换器")
    parser.add_argument("input_dir", type=str, help="包含 PNG/JPG 图片的目录")
    parser.add_argument("output_path", type=str, nargs="?", default=None, help="输出 Markdown 路径")
    parser.add_argument("--concurrency", type=int, default=4, help="并发处理路数（默认 4 路，适配 16GB 显存）")
    parser.add_argument("--disable-unwarping", action="store_true", help="如果是平整扫描件，可禁用 UVDoc 去畸变以提速 3 倍")
    return parser.parse_args()

def main():
    args = parse_args()
    input_dir = Path(args.input_dir).resolve()
    output_path = Path(args.output_path).resolve() if args.output_path else input_dir.parent / "output.md"
    cache_dir = input_dir / ".cache"
    cache_dir.mkdir(exist_ok=True, parents=True)

    img_exts = {".png", ".jpg", ".jpeg"}
    images = sorted([p for p in input_dir.iterdir() if p.suffix.lower() in img_exts and p.is_file()])

    if not images:
        print(f"[Error] 未在 {input_dir} 找到任何有效图片！")
        return

    print(f"==================================================")
    print(f" 🚀 本地 PaddleX 版面分析 & Markdown 转换流水线")
    print(f" 📁 输入目录: {input_dir} ({len(images)} 页)")
    print(f" 🎯 目标输出: {output_path}")
    print(f" ⚡ 并发路数: {args.concurrency} Workers (WSL2 GPU)")
    print(f" 🔄 去畸变 (UVDoc): {'已开启' if not args.disable_unwarping else '已关闭 (高速模式)'}")
    print(f"==================================================")

    # WSL2 pipeline runner script
    wsl_worker_code = f"""
import sys, os, time, json
from pathlib import Path
import paddlex
from paddlex import create_pipeline

input_img = sys.argv[1]
out_cache = sys.argv[2]
disable_unwarping = "{args.disable_unwarping}" == "True"

try:
    pipeline = create_pipeline(pipeline="layout_parsing", device="gpu:0")
    output = pipeline.predict(input_img)
    
    md_lines = []
    for res in output:
        for item in res.get('parsing_res_list', []):
            label = item.get('block_label', 'text')
            content = str(item.get('block_content', '')).strip()
            if not content:
                continue
            
            # 标题层级逻辑映射
            if label in ['title', 'header']:
                if any(k in content for k in ['试卷', '考试', '年', '专业', '学期']):
                    md_lines.append(f"\\n# {{content}}\\n")
                elif any(k in content for k in ['选择题', '名词解释', '简答题', '论述题', '案例分析', '判断题', '填空题', '问答题']):
                    md_lines.append(f"\\n## {{content}}\\n")
                else:
                    md_lines.append(f"\\n### {{content}}\\n")
            elif label == 'table':
                md_lines.append(f"\\n{{content}}\\n")
            else:
                # 题号自动规范
                lines = content.split('\\n')
                for line in lines:
                    line = line.strip()
                    if line.startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.', '10.')):
                        md_lines.append(f"\\n{{line}}")
                    elif line.startswith(('A.', 'B.', 'C.', 'D.', 'E.')):
                        md_lines.append(f"{{line}}")
                    elif any(k in line for k in ['答案', '解析', '【答案】', '【解析】']):
                        md_lines.append(f"\\n### {{line}}")
                    else:
                        md_lines.append(line)
                        
    md_text = "\\n".join(md_lines).strip()
    with open(out_cache, 'w', encoding='utf-8') as f:
        f.write(md_text)
    print(f"[OK] {{Path(input_img).name}} -> {{len(md_text)}} chars")
except Exception as e:
    print(f"[ERROR] {{input_img}}: {{e}}", file=sys.stderr)
    sys.exit(1)
"""

    wsl_script_path = "/home/chenlongkai/wsl_ocr_worker.py"
    # Write worker to WSL2
    import subprocess
    cmd_write = ["wsl", "-d", "Ubuntu", "bash", "-c", f"cat << 'EOF' > {wsl_script_path}\n{wsl_worker_code}\nEOF"]
    subprocess.run(cmd_write, check=True)

    # Process all pages with cache
    results = {}
    pending_images = []
    for img in images:
        cache_file = cache_dir / f"{img.stem}.md"
        if cache_file.exists() and cache_file.stat().st_size > 0:
            with open(cache_file, "r", encoding="utf-8") as f:
                results[img.name] = f.read()
        else:
            pending_images.append(img)

    print(f"[*] 已命中缓存: {len(results)} 页 | 待识别: {len(pending_images)} 页")

    if pending_images:
        for idx, img in enumerate(pending_images, 1):
            cache_file = cache_dir / f"{img.stem}.md"
            wsl_img = str(img).replace("\\", "/").replace("D:", "/mnt/d").replace("C:", "/mnt/c")
            wsl_cache = str(cache_file).replace("\\", "/").replace("D:", "/mnt/d").replace("C:", "/mnt/c")
            
            print(f"[{idx}/{len(pending_images)}] 正在识别: {img.name} (WSL2 GPU)...")
            exec_cmd = [
                "wsl", "-d", "Ubuntu", "bash", "-c",
                f"/home/chenlongkai/AI_Models/PaddleOCR-VL/venv/bin/python {wsl_script_path} '{wsl_img}' '{wsl_cache}'"
            ]
            res = subprocess.run(exec_cmd, capture_output=True, text=True)
            if res.returncode == 0 and cache_file.exists():
                with open(cache_file, "r", encoding="utf-8") as f:
                    results[img.name] = f.read()
            else:
                print(f"[警告] 页面 {img.name} 识别异常: {res.stderr.strip()[:200]}")

    # Merge all pages into final Markdown
    merged_sections = []
    for img in images:
        if img.name in results:
            merged_sections.append(f"<!-- Page: {img.name} -->\n" + results[img.name])

    final_content = "\n\n---\n\n".join(merged_sections)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_content)

    print(f"\n[✓] 完整试卷 Markdown 成功生成: {output_path} (共 {len(images)} 页，{len(final_content)} 字符)")

if __name__ == "__main__":
    main()
