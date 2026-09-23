#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从合并的 Markdown 试卷文件中提取主观题（名词解释、简答题、论述题等），
输出为可供 Anki 导入的 CSV 文件。

用法:
    python extract_for_anki.py input.md [-o output.csv] [--no-answer-hint]

输入格式:
    试卷由 # 一级标题分隔，各题型由 ## 二级标题分隔。
    题目以数字开头（如 1. 或 1、），持续到下一道题或下一个标题。
    答案/解析以 ### 答案 或 ### 解析 三级标题标识（应置于章节末尾）。

    客观题（选择题、单选题、多选题、判断题、填空题）会被自动跳过。

    答案支持的格式（### 答案 置于章节末尾，题号与题目一一对应）:
        ## 名词解释
        1. 肝掌
        2. 蜘蛛痣
        ### 答案
        1. 肝掌：大小鱼际皮肤发红，加压后退色。
        2. 蜘蛛痣：皮肤小动脉末端分支扩张。

输出:
    CSV 文件（UTF-8 BOM 编码），包含 exam, question_type, question_number,
    question_content, answer 五列，可直接导入 Anki。
"""

import argparse
import csv
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 需要提取的主观题题型
SUBJECTIVE_TYPES: set[str] = {
    "名词解释",
    "简答题",
    "论述题",
    "问答题",
    "大题",
    "病例分析",
    "案例分析",
    "综合题",
    "计算题",
    "证明题",
}

# 需要跳过的客观题题型
OBJECTIVE_TYPES: set[str] = {
    "选择题",
    "单选题",
    "多选题",
    "判断题",
    "填空题",
}

# 答案/解析章节的三级标题关键词
ANSWER_HEADINGS: set[str] = {"答案", "解析", "参考答案", "答案解析"}

# ---------------------------------------------------------------------------
# 正则表达式
# ---------------------------------------------------------------------------

# 一级标题: "# Title"（排除 "{#anchor}" 语法）
H1_RE = re.compile(r"^# (?!\{#)(.*)$")
# 二级标题: "## Title"（排除 "{#anchor}"）
H2_RE = re.compile(r"^## (?!\{#)(.*)$")
# 三级标题（任意）
H3_RE = re.compile(r"^### (?!\{#)(.*)$")
# 题目编号: "1. xxx" 或 "1、xxx"
QUESTION_NUM_RE = re.compile(r"^(\d+)[.、]\s*(.*)")
# 答案/解析三级标题: "### 答案" 等
ANSWER_H3_RE = re.compile(r"^###\s+(" + "|".join(ANSWER_HEADINGS) + r")\s*$")


def _heading_matches(heading: str, keywords: set[str]) -> bool:
    """判断二级标题文本是否包含 keywords 中的任意关键词"""
    for kw in keywords:
        if kw in heading:
            return True
    return False


# ---------------------------------------------------------------------------
# 核心解析
# ---------------------------------------------------------------------------

def parse_markdown(filepath: str) -> list[dict]:
    """
    解析 Markdown 文件，返回主观题记录列表。

    采用两阶段策略:
        阶段一 — 建立试卷 -> 题型章节的层级结构。
        阶段二 — 对每个主观题章节提取题目和答案，按题号匹配。
    """
    with open(filepath, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n\r") for line in f.readlines()]

    total = len(lines)

    # ==================================================================
    # 阶段一: 构建层级索引
    # ==================================================================

    # 试卷列表: [(名称, 起始行号, 结束行号)]
    exams: list[tuple[str, int, int]] = []

    # 题型章节列表: [(试卷名, 题型名, 起始行号, 结束行号, 是否主观题)]
    sections: list[tuple[str, str, int, int, bool]] = []

    current_exam = ""
    exam_start = 0

    for i, line in enumerate(lines):
        m1 = H1_RE.match(line)
        if m1:
            if current_exam:
                exams.append((current_exam, exam_start, i))
            current_exam = m1.group(1).strip()
            exam_start = i

    if current_exam:
        exams.append((current_exam, exam_start, total))

    for exam_name, exam_begin, exam_end in exams:
        section_start = exam_begin
        section_name = ""

        # 从 exam_begin 开始扫描题型章节（若 exam 开头无 ##，则隐式一段 fallback）
        # 实际循环从 exam_begin + 1 开始（跳过 exam 自身的 # 行）
        for i in range(exam_begin + 1, exam_end):
            line = lines[i]
            m2 = H2_RE.match(line)
            if m2:
                if section_name:
                    sections.append((
                        exam_name,
                        section_name,
                        section_start,
                        i,
                        _heading_matches(section_name, SUBJECTIVE_TYPES),
                    ))
                section_name = m2.group(1).strip()
                section_start = i

        if section_name:
            sections.append((
                exam_name,
                section_name,
                section_start,
                exam_end,
                _heading_matches(section_name, SUBJECTIVE_TYPES),
            ))

    # ==================================================================
    # 阶段二: 提取题目 + 答案
    # ==================================================================

    records: list[dict] = []

    for exam_name, section_name, sec_begin, sec_end, is_subjective in sections:
        if not is_subjective:
            continue

        sec_lines = lines[sec_begin:sec_end]

        # --- 2a. 定位题目所在行范围 ---
        # 跳过第一个 ## 标题行
        content_start = 1  # 跳过 "## xxx"
        questions_end = len(sec_lines)

        # 查找第一个 ### 答案/### 解析 标题
        answer_begin = -1
        answer_end = -1
        has_answer_block = False

        for j in range(content_start, len(sec_lines)):
            if ANSWER_H3_RE.match(sec_lines[j]):
                has_answer_block = True
                answer_begin = j
                # 答案块持续到章节末尾或下一个 ### 标题（非答案/解析）
                for k in range(j + 1, len(sec_lines)):
                    ll = sec_lines[k]
                    m = H3_RE.match(ll)
                    if m and not ANSWER_H3_RE.match(ll):
                        answer_end = k
                        break
                else:
                    answer_end = len(sec_lines)
                questions_end = j
                break

        # --- 2b. 提取题目 ---
        questions: list[dict] = []
        current_q: dict | None = None

        for j in range(content_start, questions_end):
            line = sec_lines[j]

            # 跳过无关三级标题
            if H3_RE.match(line):
                continue

            qm = QUESTION_NUM_RE.match(line)
            if qm:
                if current_q is not None:
                    questions.append(current_q)
                current_q = {
                    "number": qm.group(1),
                    "content": qm.group(2),
                }
            elif current_q is not None:
                current_q["content"] += "\n" + line
            # 忽略章节起始的介绍性文字

        if current_q is not None:
            questions.append(current_q)

        if not questions:
            continue

        # --- 2c. 提取答案 ---
        answer_text_map: dict[str, str] = {}  # question_number -> answer text

        if has_answer_block and answer_begin >= 0:
            raw_answer_lines = sec_lines[answer_begin + 1:answer_end]
            # 收集答案文本（跳过空行头和无关三级标题）
            answer_parts: list[str] = []
            for al in raw_answer_lines:
                if H3_RE.match(al) and not ANSWER_H3_RE.match(al):
                    continue
                answer_parts.append(al)

            raw_answer = "\n".join(answer_parts).strip()
            if raw_answer:
                # 尝试按题号拆分答案段落
                segments = re.split(r"\n(?=\d+[.、])", raw_answer)

                for seg in segments:
                    sqm = QUESTION_NUM_RE.match(seg)
                    if sqm:
                        num = sqm.group(1)
                        rest = re.sub(r"^\d+[.、]\s*", "", seg).strip()
                        answer_text_map[num] = rest
                    else:
                        # 属于前一段答案的延续（没有独立编号）
                        # 附加到最后一个匹配的答案里
                        if answer_text_map:
                            last_key = max(answer_text_map.keys(), key=int)
                            answer_text_map[last_key] += "\n" + seg

                # 如果拆分失败或没有对应编号，整段作为答案
                # (仅当 questions 只有 1 道时直接匹配)
                if not answer_text_map:
                    if len(questions) == 1:
                        answer_text_map[questions[0]["number"]] = raw_answer
                    else:
                        # 整段附加到最后一道题
                        answer_text_map[questions[-1]["number"]] = raw_answer

        # --- 2d. 组装记录 ---
        for q in questions:
            answer = answer_text_map.get(q["number"], "")
            records.append({
                "exam": exam_name,
                "question_type": section_name,
                "question_number": q["number"],
                "question_content": q["content"].strip(),
                "answer": answer.strip(),
            })

    return records


# ---------------------------------------------------------------------------
# CSV 输出
# ---------------------------------------------------------------------------

def write_csv(
    records: list[dict],
    output_path: str,
    no_answer_hint: bool = False,
) -> None:
    """
    将提取结果写入 CSV 文件（UTF-8 BOM 编码，兼容 Excel 中文显示）。
    自动处理内容中的逗号和换行符（使用标准 CSV 引用）。
    """
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "exam", "question_type", "question_number",
            "question_content", "answer",
        ])
        for r in records:
            answer = "" if no_answer_hint else r["answer"]
            writer.writerow([
                r["exam"],
                r["question_type"],
                r["question_number"],
                r["question_content"],
                answer,
            ])


# ---------------------------------------------------------------------------
# 统计信息
# ---------------------------------------------------------------------------

def print_statistics(records: list[dict]) -> None:
    """打印提取统计信息"""
    exams = set(r["exam"] for r in records if r["exam"])
    type_counts: dict[str, int] = {}
    answered_count = 0
    for r in records:
        qt = r["question_type"]
        type_counts[qt] = type_counts.get(qt, 0) + 1
        if r["answer"]:
            answered_count += 1

    print(f"\n{'=' * 50}")
    print(f"  提取完成！")
    print(f"{'=' * 50}")
    print(f"  共发现 {len(exams)} 份试卷")
    print(f"  共提取 {len(records)} 道主观题")
    if answered_count:
        print(f"  其中 {answered_count} 道含答案/解析")
    print(f"\n  题型分布：")
    for qt, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {qt}: {count} 题")
    print(f"{'=' * 50}\n")


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="从合并的 Markdown 试卷文件中提取主观题，输出为 Anki 可导入的 CSV 文件。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python extract_for_anki.py 试卷汇总.md\n"
            "  python extract_for_anki.py 试卷汇总.md -o anki_import.csv\n"
            "  python extract_for_anki.py 试卷汇总.md --no-answer-hint\n"
        ),
    )
    parser.add_argument("input_md", help="输入的 Markdown 文件路径")
    parser.add_argument(
        "-o", "--output",
        help="输出的 CSV 文件路径（默认：将输入文件的扩展名替换为 .csv）",
    )
    parser.add_argument(
        "--no-answer-hint",
        action="store_true",
        help="不提取答案/解析提示（即使 Markdown 中有 ### 答案/解析 内容也不包含在输出中）",
    )
    args = parser.parse_args()

    input_path = Path(args.input_md)
    if not input_path.exists():
        print(f"错误：文件不存在 — {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output) if args.output else input_path.with_suffix(".csv")

    print(f"正在解析: {input_path}")
    try:
        records = parse_markdown(str(input_path))
    except Exception as e:
        print(f"解析失败: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"正在写入: {output_path}")
    try:
        write_csv(records, str(output_path), no_answer_hint=args.no_answer_hint)
    except OSError as e:
        print(f"写入失败: {e}", file=sys.stderr)
        sys.exit(1)

    print_statistics(records)


if __name__ == "__main__":
    main()
