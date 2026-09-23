# test2anki_skills

从医学/考试类 PDF 试卷到 Anki 卡片的工具链：PDF 分页与 OCR 转 Markdown，再提取主观题并导出可导入 Anki 的 CSV。配套 Claude Code skills，便于在对话里一键跑完整流程。

## 功能

- **pdf-to-markdown**：PDF → PNG → 火山方舟多模态 OCR → 结构化 Markdown
- **anki-extract**：从 Markdown 提取名词解释、简答题、论述题等主观题，跳过选择题/填空题
- **dedup_terms**：名词解释 CSV 去重

## 目录结构

```
.claude/skills/     # Claude Code skills（工作流说明与命令约束）
scripts/            # Python 脚本
```

## 环境

```bash
cd scripts
pip install -r requirements.txt
```

火山 OCR 需在环境变量中配置 API Key（见 `volcano_md_converter.py`）。

## 快速开始

```bash
# 1. PDF → Markdown
python scripts/pdf_to_png.py exam.pdf
python scripts/volcano_md_converter.py exam_pages/

# 2. Markdown → Anki CSV
python scripts/extract_for_anki.py output.md -o cards.csv
python scripts/dedup_terms.py cards.csv -o cards_deduped.csv
```

## License

MIT
