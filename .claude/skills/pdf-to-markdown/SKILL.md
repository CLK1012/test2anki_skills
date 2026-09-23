---
name: pdf-to-markdown
description: "PDF, 试卷, OCR, 转markdown, 数字化试卷: Split PDF exam papers into PNG images, convert to JPEG if needed, then OCR via Volcano Ark multimodal model to produce structured Markdown. Supports 30 concurrent requests with automatic cache and resume."
allowed-tools:
  - Read
  - Bash(mkdir -p d:/project/mid_anki/*)
  - Bash(PYTHONIOENCODING=utf-8 python d:/project/anki-processing/scripts/pdf_to_png.py *)
  - Bash(SSL_CERT_FILE=* PYTHONIOENCODING=utf-8 python d:/project/anki-processing/scripts/volcano_md_converter.py *)
---

# PDF Exam Paper -> Markdown

Convert PDF exam papers into structured Markdown for downstream extraction and Anki import.

## Working Directory

Always use `D:\project\mid_anki` as the workspace for generated files.

For each new PDF/OCR task:

1. Create a fresh subdirectory under `D:\project\mid_anki`, using `YYYYMMDD-HHMMSS-short-name`.
2. Put generated PNG/JPEG pages, cache files, and Markdown output inside that task subdirectory.
3. Put command logs in that task subdirectory as `pdf_to_png.log` and `ocr.log` when capturing output.
4. Prefer foreground commands. If Claude Code still runs a long command in the background, its own tool transcript may be stored under `%LOCALAPPDATA%\Temp\claude`; this is Claude Code's internal task log and cannot be fully controlled by this skill.
5. Do not write generated outputs beside the source PDF unless the user explicitly asks for that.

## Pipeline

```
PDF file --> [pdf_to_png.py] --> PNG files --> [volcano_md_converter.py] --> Merged Markdown
                                              (auto-converts to JPEG if >10 MiB)
```

## Environment Requirements

Three critical environment variables must be set for every Python invocation in this pipeline:

| Variable | Value | Why |
|----------|-------|-----|
| `PYTHONIOENCODING` | `utf-8` | Prevents `UnicodeEncodeError` on GBK terminals when emoji (⚠ ✓ ✗) are printed |
| `SSL_CERT_FILE` | `C:/Conda/Lib/site-packages/certifi/cacert.pem` | Fixes `_ssl.c:2406 unknown error` on Windows Conda Python when sending large POST bodies |
| (script paths) | **Absolute paths only** | Relative paths like `../../../scripts/...` break when CWD ≠ skill directory |

> **Important:** Always invoke Python **directly** (not through `powershell -NoProfile -Command`). PowerShell adds a layer that drops env vars and re-encodes output.

## Step 1: Split PDF to PNGs

```bash
mkdir -p d:/project/mid_anki/YYYYMMDD-HHMMSS-short-name/pages
PYTHONIOENCODING=utf-8 python d:/project/anki-processing/scripts/pdf_to_png.py "<pdf-path>" d:/project/mid_anki/YYYYMMDD-HHMMSS-short-name/pages --dpi 300 2>&1 | tee d:/project/mid_anki/YYYYMMDD-HHMMSS-short-name/pdf_to_png.log
```

- Images named: `page_001.png`, `page_002.png`, ...
- Default 300 DPI. If individual PNGs exceed ~50 MB, consider lowering to `--dpi 150` or `--dpi 100`. The downstream converter will auto-convert oversized images to JPEG, but starting smaller speeds up I/O.

## Step 2: OCR Images via Volcano Ark

```bash
SSL_CERT_FILE="C:/Conda/Lib/site-packages/certifi/cacert.pem" PYTHONIOENCODING=utf-8 python d:/project/anki-processing/scripts/volcano_md_converter.py d:/project/mid_anki/YYYYMMDD-HHMMSS-short-name/pages d:/project/mid_anki/YYYYMMDD-HHMMSS-short-name/output.md --concurrency 30 2>&1 | tee d:/project/mid_anki/YYYYMMDD-HHMMSS-short-name/ocr.log
```

- Default concurrency: 30
- **Auto image preparation:** If any image file exceeds the API's 10 MiB limit, the converter automatically converts it to JPEG (and resizes if needed). No manual PNG→JPEG step required.
- Intermediate results cached at `<image-dir>/.cache/` for resume
- API failures auto-retry 3 times (exponential backoff)
- Supported input formats: `.png`, `.jpg`, `.jpeg`

## Model Configuration

| Parameter | Value |
|-----------|-------|
| Model | `doubao-seed-2-0-lite-260428` |
| Endpoint | `https://ark.cn-beijing.volces.com/api/v3/chat/completions` |
| Auth | Bearer Token (pre-configured in script) |
| Max image size | 10 MiB (auto-converted if exceeded) |

## OCR System Prompt

Each image is processed with the following instructions:

1. Multi-column layout: read left to right column by column
2. Year + major -> level-1 heading `#`
3. Question type -> level-2 heading `##`
4. Preserve original sub-question numbering; auto-number if missing
5. Output all characters accurately as Markdown
6. Mark answers/solutions with level-3 heading `###`

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `UnicodeEncodeError: 'gbk' codec can't encode` | Windows terminal uses GBK, emoji characters fail | Set `PYTHONIOENCODING=utf-8` |
| `SSLError: unknown error (_ssl.c:2406)` | Conda Python SSL cert on Windows | Set `SSL_CERT_FILE` to certifi bundle (see above) |
| `HTTP 400: OversizeImage` / "exceeds the limit (10 MiB)" | PNG too large for API | Lower `--dpi` in Step 1, or the converter auto-converts to JPEG |
| `HTTP 400` without clear message | Image dimensions may exceed API limits | Check API response body in ocr.log; try `--dpi 100` |

## Examples

```bash
# Full pipeline — 2023 clinical medicine exam
mkdir -p d:/project/mid_anki/20260605-143000-2023-clinical/pages
PYTHONIOENCODING=utf-8 python d:/project/anki-processing/scripts/pdf_to_png.py "2023 clinical medicine exam.pdf" d:/project/mid_anki/20260605-143000-2023-clinical/pages --dpi 300 2>&1 | tee d:/project/mid_anki/20260605-143000-2023-clinical/pdf_to_png.log
SSL_CERT_FILE="C:/Conda/Lib/site-packages/certifi/cacert.pem" PYTHONIOENCODING=utf-8 python d:/project/anki-processing/scripts/volcano_md_converter.py d:/project/mid_anki/20260605-143000-2023-clinical/pages d:/project/mid_anki/20260605-143000-2023-clinical/output.md --concurrency 30 2>&1 | tee d:/project/mid_anki/20260605-143000-2023-clinical/ocr.log
```

## Dependencies

Ensure the virtual environment is active and dependencies are installed:

```bash
pip install -r d:/project/anki-processing/scripts/requirements.txt
```

Key packages: `PyMuPDF` (fitz), `Pillow`, `requests`, `certifi`.

The Volcano API key is already configured in the scripts.
