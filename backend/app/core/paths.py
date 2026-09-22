from pathlib import Path

# 本文件位于 backend/app/core/paths.py，向上回溯三级即为项目根目录。
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent

ENV_FILE = PROJECT_ROOT / ".env"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
