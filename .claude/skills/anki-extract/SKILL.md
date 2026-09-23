---
name: anki-extract
description: "提取主观题, 生成anki, 名词解释提取, 导出anki卡片, Anki CSV: Extract subjective exam questions (名词解释, 简答题, 论述题) from OCR'd Markdown exam papers and export to Anki-importable CSV. Skips objective questions automatically."
allowed-tools:
  - Read
  - Bash(mkdir -p d:/project/mid_anki/*)
  - Bash(powershell -NoProfile -Command *)
  - Bash(python ../../../scripts/extract_for_anki.py *)
  - Bash(python ../../../scripts/dedup_terms.py *)
---

# Subjective Question Extraction -> Anki CSV

Extract subjective questions from Markdown exam papers and generate CSV files ready for Anki import.

## Working Directory

Always use `D:\project\mid_anki` as the workspace for generated files.

For each new extraction/import task:

1. Create a fresh subdirectory under `D:\project\mid_anki`, using `YYYYMMDD-HHMMSS-short-name`.
2. Put extracted CSV files, deduped CSV files, and import-ready outputs inside that task subdirectory.
3. If the input Markdown was produced by `pdf-to-markdown`, reuse that existing task subdirectory instead of creating a second one.
4. Put command logs in that task subdirectory as `extract.log` and `dedup.log` when capturing output.
5. Prefer foreground commands. If Claude Code still runs a long command in the background, its own tool transcript may be stored under `%LOCALAPPDATA%\Temp\claude`; this is Claude Code's internal task log and cannot be fully controlled by this skill.
6. Do not write generated outputs beside the source Markdown unless the user explicitly asks for that.

## Usage

```bash
mkdir -p d:/project/mid_anki/YYYYMMDD-HHMMSS-short-name
powershell -NoProfile -Command "python ../../../scripts/extract_for_anki.py '<input-md>' -o d:/project/mid_anki/YYYYMMDD-HHMMSS-short-name/cards.csv 2>&1 | Tee-Object -FilePath d:/project/mid_anki/YYYYMMDD-HHMMSS-short-name/extract.log"
```

## Extraction Rules

| Rule | Description |
|------|-------------|
| Exam ID | Extracted from `#` level-1 heading (e.g., "2023 Clinical Medicine") |
| Question type | Extracted from `##` level-2 heading |
| **Extracted** | 名词解释, 简答题, 论述题, 问答题, 大题, 病例分析, 案例分析, 综合题, 计算题, 证明题 |
| **Skipped** | 选择题, 单选题, 多选题, 判断题, 填空题 |
| Answer extraction | From `### 答案` / `### 解析` content, matched by question number |
| Question number | Original numbering preserved |

## CSV Output Format

UTF-8 BOM CSV with 5 columns:

| Column | Content |
|--------|---------|
| `exam` | Exam ID (year + major) |
| `question_type` | Type (名词解释/简答题/...) |
| `question_number` | Question number |
| `question_content` | Question body |
| `answer` | Answer/solution (if available) |

## Options

- `-o, --output <path>`: Output CSV path (default: same directory as input, `.csv` extension)
- `--no-answer-hint`: Skip answer extraction, leave answer column blank

## Deduplication Strategy

After extracting questions from multiple exam papers, duplicates should be removed before final Anki import.

### For 名词解释 (Term Explanations)

Run the dedicated dedup script:

```bash
powershell -NoProfile -Command "python ../../../scripts/dedup_terms.py d:/project/mid_anki/YYYYMMDD-HHMMSS-short-name/cards.csv -o d:/project/mid_anki/YYYYMMDD-HHMMSS-short-name/cards.deduped.csv 2>&1 | Tee-Object -FilePath d:/project/mid_anki/YYYYMMDD-HHMMSS-short-name/dedup.log"
```

This uses fuzzy matching to identify and remove duplicate term explanations.

### For 大题 (Essay Questions: 简答题/论述题/问答题 etc.)

Essay questions have longer, more complex content that may be phrased differently across years. String-only fuzzy matching is insufficient. Instead:

1. Claude Code will autonomously dispatch a sub-agent (Agent with subagent_type="general-purpose") to review and deduplicate
2. The sub-agent reads the CSV, compares essay questions by semantic meaning (not just string similarity), flags duplicates, and outputs a cleaned CSV
3. **Before running the essay dedup sub-agent, Claude Code MUST ask the user for confirmation**

## Anki Import

### Method 1: CSV Manual Import

1. In Anki desktop: `File > Import`
2. Select the CSV file
3. Map CSV columns to note fields
4. Ensure the CSV delimiter matches Anki's expectation (tab or comma)

### Method 2: Anki-MCP Server (Recommended)

Use the MCP tool `batch_create_notes` to import directly into Anki:

```
- Connect via Anki-MCP Server
- Create a note type matching the CSV schema
- Use batch_create_notes with the extracted data
```

## Dependencies

Ensure the virtual environment is active and dependencies are installed:

```bash
pip install -r ../../../scripts/requirements.txt
```

The Volcano API key is already configured in the scripts.
