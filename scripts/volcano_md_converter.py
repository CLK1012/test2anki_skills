#!/usr/bin/env python3
"""
volcano_md_converter.py — 将图片发送至火山方舟 Ark API 转换为 Markdown

用法:
    python volcano_md_converter.py <input_dir> [output_path] [--concurrency 30] [--max-size-mb 10]

说明:
    - 输入目录应包含 page_001.png, page_002.png, ... 等图片（pdf_to_png.py 的输出）。
    - 支持 PNG / JPEG 输入；超过 --max-size-mb（默认 10 MiB）的图片自动转 JPEG 或缩小。
    - 每张图片通过火山方舟多模态大模型识别并转为 Markdown。
    - 中间结果实时缓存至 <input_dir>/.cache/page_xxx.md，不因中断丢失。
    - 转换后的 JPEG 缓存至 <input_dir>/.cache/prepared/，避免重复转换。
    - 最终合并所有缓存结果为单个 Markdown 文件，以 --- 分页。
"""

import argparse
import base64
import os
import sys
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from PIL import Image

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
API_BASE = "https://ark.cn-beijing.volces.com/api/v3"
API_KEY = os.environ.get("VOLCENGINE_API_KEY", "")
MODEL = "doubao-seed-2-0-lite-260428"
MAX_IMAGE_MB = 10  # 火山 Ark API 单张图片上限
SYSTEM_PROMPT = """你是一个专业的试卷数字化助手。请按照以下规则将图片中的试卷内容转化为markdown格式：

1. 对于多栏排版的试卷，按照从左到右逐栏阅读，每一栏内部从上到下阅读的顺序处理。
2. 将试卷的"年份+专业"标识（如"2023年临床医学专业"）使用markdown一级标题（# ）显示。
3. 将题型（选择题、名词解释、简答题、论述题、判断题、填空题、问答题等）使用markdown二级标题（## ）显示。
4. 具体的小题号保留原有的数字序号（如1、2、3），没有序号的题目用阿拉伯数字序号补全。
5. 将输入图片中的所有字符准确无误地输出为markdown，包括题目内容、选项、标点符号等。
6. 选择题的选项保留原样（如A. B. C. D.）。
7. 如果图片中包含答案或解析，也一并输出，使用三级标题（### ）标注"答案"或"解析"。
8. 对于表格、公式等特殊内容，尽量用markdown表格或LaTeX公式还原。"""

MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # 秒
REQUEST_TIMEOUT = 120   # 秒
CACHE_DIR_NAME = ".cache"


# ---------------------------------------------------------------------------
# 命令行参数
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="将 PNG 图片发送至火山方舟 Ark API 转换为 Markdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python volcano_md_converter.py ./input_pages\n"
            "  python volcano_md_converter.py ./input_pages ./output.md --concurrency 10\n"
        ),
    )
    parser.add_argument("input_dir", type=str, help="包含 PNG 图片的目录")
    parser.add_argument(
        "output_path",
        type=str,
        nargs="?",
        default=None,
        help="输出 Markdown 文件路径（默认: <input_dir>/../output.md）",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=30,
        help="并发请求数（默认: 30）",
    )
    parser.add_argument(
        "--max-size-mb",
        type=int,
        default=MAX_IMAGE_MB,
        help=f"图片大小上限（MiB），超过则自动转 JPEG/缩放（默认: {MAX_IMAGE_MB}）",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 图片处理与 API 调用
# ---------------------------------------------------------------------------
def encode_image(image_path: Path) -> tuple[str, str]:
    """读取图片文件并返回 (base64 编码字符串, mime_type)"""
    suffix = image_path.suffix.lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
    mime_type = mime_map.get(suffix, "image/png")
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8"), mime_type


def prepare_image(image_path: Path, cache_dir: Path, max_mb: int = MAX_IMAGE_MB) -> Path:
    """
    为 API 调用准备图片：若文件大小超过 max_mb，自动转为 JPEG，
    必要时进一步缩小尺寸。返回最终应使用的图片路径。

    生成的 JPEG 缓存于 cache_dir/prepared/ 子目录，避免重复转换。
    """
    size_mb = image_path.stat().st_size / (1024 * 1024)
    if size_mb <= max_mb:
        return image_path

    # 准备输出路径
    prepared_dir = cache_dir / "prepared"
    prepared_dir.mkdir(parents=True, exist_ok=True)
    jpg_path = prepared_dir / f"{image_path.stem}.jpg"

    # 如果已转换过且不超标，直接复用
    if jpg_path.exists() and jpg_path.stat().st_size / (1024 * 1024) <= max_mb:
        print(f"  ↪ {image_path.name} 已有转换缓存 ({jpg_path.stat().st_size / 1024 / 1024:.1f} MB)")
        return jpg_path

    img = Image.open(image_path)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # 逐步降 quality，再降分辨率
    for quality in (85, 70, 55):
        img.save(jpg_path, "JPEG", quality=quality)
        new_mb = jpg_path.stat().st_size / (1024 * 1024)
        if new_mb <= max_mb:
            print(f"  ↪ {image_path.name} ({size_mb:.1f} MB) 转 JPEG quality={quality} → {new_mb:.1f} MB")
            return jpg_path

    # quality 55 仍超标，等比例缩小尺寸
    w, h = img.size
    scale = (max_mb / (jpg_path.stat().st_size / (1024 * 1024))) ** 0.5 * 0.9
    new_size = (int(w * scale), int(h * scale))
    img_resized = img.resize(new_size, Image.LANCZOS)
    img_resized.save(jpg_path, "JPEG", quality=55)
    new_mb = jpg_path.stat().st_size / (1024 * 1024)
    print(f"  ↪ {image_path.name} ({size_mb:.1f} MB) 缩放 {w}x{h}→{new_size[0]}x{new_size[1]} JPEG → {new_mb:.1f} MB")
    return jpg_path


def call_ark_api(image_base64: str, mime_type: str = "image/png") -> str:
    """
    调用火山方舟 Ark API，将图片转为 Markdown。

    参数:
        image_base64: PNG 图片的 base64 编码字符串

    返回:
        API 返回的 Markdown 文本内容

    抛出:
        requests.RequestException: 请求失败（调用方处理重试）
        ValueError: API 返回异常结果
    """
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_base64}"
                        },
                    }
                ],
            },
        ],
    }

    resp = requests.post(
        f"{API_BASE}/chat/completions",
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT,
        proxies={"http": None, "https": None},
    )
    resp.raise_for_status()

    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        raise ValueError(f"API 返回的 choices 为空: {data}")

    content = choices[0].get("message", {}).get("content", "")
    return content.strip()


def process_one_page(
    image_path: Path, cache_path: Path, max_mb: int = MAX_IMAGE_MB
) -> tuple[Path, bool]:
    """
    处理单张图片：准备（含自动转 JPEG）-> API 调用（含重试）-> 写入缓存。

    返回:
        (image_path, success_flag)
    """
    if cache_path.exists():
        print(f"  ✓ {image_path.name} 已缓存，跳过")
        return (image_path, True)

    # --- 图片准备：超大文件自动转 JPEG ---
    cache_dir = cache_path.parent
    prepared_path = prepare_image(image_path, cache_dir, max_mb)

    print(f"  开始处理: {prepared_path.name}")
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            encoded, mime_type = encode_image(prepared_path)
            markdown_text = call_ark_api(encoded, mime_type)
            # 写入缓存文件
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(markdown_text, encoding="utf-8")
            print(f"  ✓ {prepared_path.name} 完成 (尝试 {attempt})")
            return (image_path, True)
        except requests.exceptions.Timeout as e:
            last_error = e
            print(f"  ⚠ {prepared_path.name} 超时 (尝试 {attempt}/{MAX_RETRIES})")
        except requests.exceptions.HTTPError as e:
            last_error = e
            status = e.response.status_code if e.response is not None else "?"
            # 打印 API 返回的错误详情，便于诊断
            detail = ""
            if e.response is not None:
                try:
                    detail = e.response.text[:500]
                except Exception:
                    pass
            print(f"  ⚠ {prepared_path.name} HTTP {status} (尝试 {attempt}/{MAX_RETRIES})")
            if detail:
                print(f"    API 响应: {detail}")
            # 4xx 错误（除 429 限流外）不重试
            if e.response is not None and 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                print(f"  ✗ {prepared_path.name} 非可重试错误，跳过")
                return (image_path, False)
        except (requests.RequestException, ValueError) as e:
            last_error = e
            print(f"  ⚠ {prepared_path.name} 请求失败: {e} (尝试 {attempt}/{MAX_RETRIES})")

        if attempt < MAX_RETRIES:
            # 指数退避 + 随机抖动
            sleep_time = INITIAL_BACKOFF * (2 ** (attempt - 1)) + random.uniform(0, 1.0)
            print(f"    {sleep_time:.1f}s 后重试...")
            time.sleep(sleep_time)

    print(f"  ✗ {prepared_path.name} 处理失败（已重试 {MAX_RETRIES} 次）")
    if last_error is not None:
        print(f"    最后错误: {last_error}")
    return (image_path, False)


# ---------------------------------------------------------------------------
# 收集与合并结果
# ---------------------------------------------------------------------------
def collect_image_files(input_dir: Path) -> list[Path]:
    """
    扫描输入目录，按文件名排序返回所有图片文件路径（PNG 和 JPEG）。

    支持 page_001.png/page_001.jpg 及自定义命名，按自然顺序排列。
    """
    image_files = sorted(input_dir.glob("*.png")) + sorted(input_dir.glob("*.jpg")) + sorted(input_dir.glob("*.jpeg"))
    if not image_files:
        print(f"错误: 目录 '{input_dir}' 中未找到任何图片文件", file=sys.stderr)
        sys.exit(1)
    return image_files


def resolve_output_path(input_dir: Path, output_path: str | None) -> Path:
    """确定最终的 Markdown 输出路径"""
    if output_path:
        out = Path(output_path)
    else:
        out = input_dir.parent / "output.md"
    return out


def get_cache_dir(input_dir: Path) -> Path:
    """返回缓存目录路径"""
    return input_dir / CACHE_DIR_NAME


def get_cache_path(cache_dir: Path, image_path: Path) -> Path:
    """返回某张图片对应的缓存文件路径"""
    return cache_dir / f"{image_path.stem}.md"


def combine_cache_to_output(cache_dir: Path, output_path: Path) -> int:
    """
    将缓存目录中所有 .md 文件按文件名顺序合并到最终输出文件。

    返回成功合并的页数。如果某个缓存文件缺失，打印警告并跳过。
    """
    cache_files = sorted(cache_dir.glob("*.md"))
    if not cache_files:
        print("警告: 缓存目录中没有找到任何 .md 文件", file=sys.stderr)
        return 0

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with open(output_path, "w", encoding="utf-8") as out:
        for idx, cache_file in enumerate(cache_files):
            if not cache_file.is_file():
                print(f"  警告: 缓存文件缺失 — {cache_file.name}")
                continue
            content = cache_file.read_text(encoding="utf-8")
            if idx > 0:
                out.write("\n\n---\n\n")
            out.write(content)
            written += 1

    print(f"已合并 {written} 页到: {output_path}")
    return written


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> None:
    """主函数"""
    args = parse_args()
    input_dir = Path(args.input_dir).resolve()
    if not input_dir.is_dir():
        print(f"错误: 输入目录不存在 — {input_dir}", file=sys.stderr)
        sys.exit(1)

    output_path = resolve_output_path(input_dir, args.output_path)
    cache_dir = get_cache_dir(input_dir)
    png_files = collect_image_files(input_dir)

    print(f"火山方舟 Markdown 转换工具")
    print(f"输入目录: {input_dir}")
    print(f"图片数量: {len(png_files)}")
    print(f"输出文件: {output_path}")
    print(f"缓存目录: {cache_dir}")
    print(f"并发数:   {args.concurrency}")
    print(f"模型:     {MODEL}")
    print("-" * 50)

    # --- 并发处理所有图片 ---
    print("开始转换...")
    success_count = 0
    fail_count = 0

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        future_map = {}
        for img_path in png_files:
            cache_path = get_cache_path(cache_dir, img_path)
            future = executor.submit(process_one_page, img_path, cache_path, args.max_size_mb)
            future_map[future] = img_path

        for future in as_completed(future_map):
            img_path, success = future.result()
            if success:
                success_count += 1
            else:
                fail_count += 1

    # --- 合并缓存文件为最终输出 ---
    print("-" * 50)
    print(f"转换完成: 成功 {success_count}, 失败 {fail_count} / 总计 {len(png_files)}")

    if success_count > 0:
        print("正在合并缓存文件...")
        combined = combine_cache_to_output(cache_dir, output_path)
        print(f"最终输出文件: {output_path} ({combined} 页)")
    else:
        print("没有成功转换的页面，跳过合并。")
        sys.exit(1)

    if fail_count > 0:
        print(f"注意: 有 {fail_count} 页处理失败，请检查缓存目录中的缺失文件。")
        sys.exit(1)


if __name__ == "__main__":
    main()
