#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
去重脚本：去除提取的 CSV 中重复的「名词解释」题目。

输入 CSV 列：exam, question_type, question_number, question_content, answer
仅对 question_type == "名词解释" 的行进行去重，保留最佳版本并输出新 CSV。

用法：
    python dedup_terms.py input.csv
    python dedup_terms.py input.csv -o output.csv
    python dedup_terms.py input.csv --threshold 0.85
"""

import argparse
import csv
import os
import re
import sys
import unicodedata


# ---------------------------------------------------------------------------
# 文本规范化与相似度判断
# ---------------------------------------------------------------------------

# CJK 统一表意文字范围（用于区分中文和注释内容）
_CJK_RANGE = re.compile(r'[一-鿿]')


def _is_cjk(char: str) -> bool:
    """判断单个字符是否为 CJK 统一表意文字。"""
    return '一' <= char <= '鿿'


def normalize_text(text: str) -> str:
    """
    规范化文本用于去重比较。

    步骤：
    1. 全角符号 -> 半角（NFKC 规范化）
    2. 转小写
    3. 移除所有空白字符
    4. 移除常见中英文标点符号
    """
    if not text:
        return ""

    # 全角转半角
    text = unicodedata.normalize("NFKC", text)
    # 转小写
    text = text.lower()
    # 去除所有空白字符
    text = re.sub(r'\s+', '', text)
    # 去除常见标点符号
    punct_chars = (
        '、。，；：！？（）'        # Chinese punctuation
        '【】《》""「」『'          # Chinese brackets & quotes
        '』〔〕—…・・'                       # other Chinese punct
        '[]{}()<>,?!;:-_#@&*+=/|~`^'  # ASCII punctuation
        "\"'"
    )
    text = re.sub(f'[{re.escape(punct_chars)}]', '', text)
    return text


def extract_cjk(text: str) -> str:
    """仅提取字符串中的 CJK 字符，用于纯中文内容的比较。"""
    return ''.join(c for c in text if _is_cjk(c))


def is_duplicate(content_a: str, content_b: str) -> bool:
    """
    判断两个 question_content 是否为重复项。

    判定规则（优先级从高到低）：
    1. 去除首尾空白后完全一致 -> 重复
    2. 规范化后完全一致 -> 重复
    3. 仅提取 CJK 部分后完全一致 -> 重复（忽略外语注释差异）
    4. 其中一个被另一个包含，且多出的部分不含中文 -> 重复（如 "肝掌" vs "肝掌（hepatic palm）"）

    返回 True 表示两个内容是重复的。
    """
    a_stripped = (content_a or "").strip()
    b_stripped = (content_b or "").strip()

    # 规则 1：直接比较
    if a_stripped and b_stripped and a_stripped == b_stripped:
        return True

    a_norm = normalize_text(content_a)
    b_norm = normalize_text(content_b)

    if not a_norm or not b_norm:
        return False

    # 规则 2：规范化后一致
    if a_norm == b_norm:
        return True

    # 规则 3：仅比较 CJK 部分
    a_cjk = extract_cjk(a_norm)
    b_cjk = extract_cjk(b_norm)
    if a_cjk and b_cjk and a_cjk == b_cjk:
        return True

    # 规则 4：包含关系 + 多余部分无中文
    shorter, longer = (a_norm, b_norm) if len(a_norm) <= len(b_norm) else (b_norm, a_norm)
    if len(shorter) < 2:
        # 避免单字符的误匹配
        return False

    idx = longer.find(shorter)
    if idx == -1:
        return False

    prefix = longer[:idx]
    suffix = longer[idx + len(shorter):]
    extra = prefix + suffix

    # 多余部分不含任何 CJK 字符（纯字母/数字/符号）→ 视为注释变体
    if not _CJK_RANGE.search(extra):
        return True

    return False


def pick_best(rows: list) -> dict:
    """
    从一组重复行中选出最佳版本。

    优先级：
    1. 有 answer 优于无 answer
    2. answer 更长更优（更详细）
    3. question_content 更长更优（更多上下文）
    """
    def sort_key(row):
        answer = (row.get("answer") or "").strip()
        question = (row.get("question_content") or "").strip()
        # 主：有答案 (1) / 无答案 (0)
        # 次：答案长度
        # 末：题目内容长度
        return (1 if answer else 0, len(answer), len(question))
    return max(rows, key=sort_key)


# ---------------------------------------------------------------------------
# 主去重逻辑
# ---------------------------------------------------------------------------

def dedup_terms(input_path: str, output_path: str, threshold: float = 0.85) -> None:
    """
    执行去重主流程。

    参数：
        input_path  : 输入 CSV 路径
        output_path : 输出 CSV 路径
        threshold   : 保留参数，预留未来相似度阈值（当前使用规则匹配）
    """
    # 抑制未使用的参数警告（threshold 留作将来扩展）
    _ = threshold

    # 1. 读取所有行
    all_rows: list[dict] = []
    with open(input_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if not fieldnames:
            print("错误：CSV 文件为空或缺少表头行")
            sys.exit(1)
        for row in reader:
            all_rows.append(row)

    # 2. 分离名词解释行与其他题型行
    term_rows: list[dict] = []
    other_rows: list[dict] = []
    for row in all_rows:
        qtype = (row.get("question_type") or "").strip()
        if qtype == "名词解释":
            term_rows.append(row)
        else:
            other_rows.append(row)

    total_terms = len(term_rows)
    if total_terms == 0:
        # 没有名词解释，直接写回原内容
        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_rows)
        print("提示：CSV 中未找到任何「名词解释」行，直接输出原文件。")
        return

    # 3. 聚类：将互为重复的行归入同一组
    groups: list[list[int]] = []       # 每组存的是 term_rows 中的索引
    for i in range(len(term_rows)):
        content_i = term_rows[i].get("question_content") or ""
        matched_group_indices: list[int] = []

        for g_idx, group in enumerate(groups):
            # 如果当前行与组内任意成员重复，则匹配该组
            for idx in group:
                if is_duplicate(content_i, term_rows[idx].get("question_content") or ""):
                    matched_group_indices.append(g_idx)
                    break

        if not matched_group_indices:
            # 无匹配 → 新建一组
            groups.append([i])
        else:
            target = matched_group_indices[0]
            groups[target].append(i)
            # 若有多个匹配的组，则合并
            for mg in sorted(matched_group_indices[1:], reverse=True):
                groups[target].extend(groups[mg])
                groups.pop(mg)

    # 4. 从每组中选出最佳版本
    kept_indices: set[int] = set()
    removed_details: list[list[dict]] = []   # 每个元素对应一个重复组

    for group in groups:
        if len(group) == 1:
            kept_indices.add(group[0])
        else:
            group_rows = [term_rows[i] for i in group]
            best = pick_best(group_rows)

            # 在 group_rows 中找到 best 的位置
            best_in_group = group_rows.index(best)
            best_original_idx = group[best_in_group]
            kept_indices.add(best_original_idx)

            # 记录被移除的行
            removed: list[dict] = []
            for gi, row in enumerate(group_rows):
                if gi == best_in_group:
                    continue
                removed.append({
                    "old_exam":    (row.get("exam") or "").strip(),
                    "old_content": (row.get("question_content") or "").strip(),
                    "kept_exam":    (best.get("exam") or "").strip(),
                    "kept_content": (best.get("question_content") or "").strip(),
                })
            if removed:
                removed_details.append(removed)

    # 5. 组装输出行（名词解释保留行 + 其他题型行，保持原始顺序）
    kept_term_rows = [term_rows[i] for i in sorted(kept_indices, key=lambda x: x)]
    output_rows = kept_term_rows + other_rows

    # 6. 写入 CSV
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    # 7. 输出统计信息
    kept_count = len(kept_term_rows)
    removed_count = total_terms - kept_count
    dup_group_count = sum(1 for g in groups if len(g) > 1)

    sep = "=" * 60
    print(sep)
    print("去重完成！")
    print(sep)
    print(f"  输入文件:           {input_path}")
    print(f"  输出文件:           {output_path}")
    print(f"  名词解释总行数:     {total_terms}")
    print(f"  去重后保留:        {kept_count}")
    print(f"  删除重复:          {removed_count}")
    print(f"  重复组数量:        {dup_group_count}")
    print()

    if removed_details:
        print(sep)
        print("被移除的重复项详情：")
        print(sep)
        for r_idx, group in enumerate(removed_details, 1):
            print(f"\n  重复组 #{r_idx}:")
            for item in group:
                print(f"    移除: [{item['old_exam']}] {item['old_content']}")
            # 最后一条 item 仍在循环中，用其保留信息
            print(f"    保留: [{item['kept_exam']}] {item['kept_content']}")

    print(sep)


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="去除提取的 CSV 中重复的「名词解释」题目",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python dedup_terms.py input.csv\n"
            "  python dedup_terms.py input.csv -o output.csv\n"
            "  python dedup_terms.py input.csv --threshold 0.90\n"
        ),
    )
    parser.add_argument("input_csv", help="输入的 CSV 文件路径")
    parser.add_argument(
        "-o", "--output",
        help="输出的 CSV 文件路径（默认: 输入文件名 _deduped.csv）",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="保留参数，预留未来相似度阈值（当前使用规则匹配，默认: 0.85）",
    )

    args = parser.parse_args()

    # 校验输入文件
    input_path = args.input_csv
    if not os.path.isfile(input_path):
        print(f"错误：文件不存在 - {input_path}")
        sys.exit(1)

    # 确定输出路径
    output_path = args.output
    if not output_path:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_deduped.csv"

    # 避免覆盖输入文件
    if os.path.abspath(output_path) == os.path.abspath(input_path):
        print("错误：输出文件不能与输入文件相同，请使用 -o 指定不同的输出路径。")
        sys.exit(1)

    dedup_terms(input_path, output_path, args.threshold)


if __name__ == "__main__":
    main()
