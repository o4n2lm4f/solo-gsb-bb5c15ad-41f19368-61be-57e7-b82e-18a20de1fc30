"""运行期配置：全部可通过环境变量覆盖。"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# SQLite 数据库文件路径（容器内默认 /app/data/addresses.db）
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "addresses.db"))

# 匹配阈值
MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", "0.80"))  # 最高分低于此值 -> 待确认
MATCH_MARGIN = float(os.getenv("MATCH_MARGIN", "0.05"))        # 前两名分差小于此值 -> 待确认
MATCH_FLOOR = float(os.getenv("MATCH_FLOOR", "0.30"))          # 最高分低于此值 -> 无匹配
TOP_K = int(os.getenv("TOP_K", "5"))                           # 每条地址保留的候选数

# 首次启动且标准库为空时，自动导入示例数据
LOAD_SAMPLE_DATA = os.getenv("LOAD_SAMPLE_DATA", "0") not in ("0", "false", "False", "")
SAMPLE_DATA_PATH = BASE_DIR / "sample_data" / "standard_addresses.csv"

# 相似度权重：词元相似度 / 门牌号相似度
TOKEN_WEIGHT = float(os.getenv("TOKEN_WEIGHT", "0.68"))
NUMBER_WEIGHT = 1.0 - TOKEN_WEIGHT
# 一方缺少门牌号时给出的中性相似度（不能直接判 0，街道本身可能完全一致）
MISSING_NUMBER_SIM = float(os.getenv("MISSING_NUMBER_SIM", "0.5"))
# 词元模糊匹配（difflib）视为命中的最低比率
FUZZY_TOKEN_RATIO = float(os.getenv("FUZZY_TOKEN_RATIO", "0.82"))
