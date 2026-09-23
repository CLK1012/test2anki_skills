# ---------------------------------------------------------------------------
# API 与模型配置模板 (config.example.py)
# 复制本文件为 config.py，并填入真实的 API Key
# 注意：config.py 已被加入 .gitignore，绝不会被提交到远程仓库！
# ---------------------------------------------------------------------------
import os

# 1. 火山方舟 (Volcengine Ark) API 配置
# 可在火山引擎控制台获取 API Key
VOLCENGINE_API_KEY = os.environ.get("VOLCENGINE_API_KEY", "")
VOLCENGINE_API_BASE = "https://ark.cn-beijing.volces.com/api/v3"
VOLCENGINE_MODEL = "doubao-seed-2-0-lite-260428"

# 2. 其他多模态 VLM / 大语言模型预留配置 (未来扩展)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# 3. 本地 OCR 与处理配置
MAX_IMAGE_MB = 10
REQUEST_TIMEOUT = 120
MAX_RETRIES = 3
DEFAULT_CONCURRENCY = 30
