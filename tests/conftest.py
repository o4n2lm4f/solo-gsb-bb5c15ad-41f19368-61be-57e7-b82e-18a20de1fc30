import os
import sys
import tempfile

import pytest

# 在导入应用前指定临时数据库（config 在导入时读取环境变量）
_TMP = tempfile.mkdtemp(prefix="addrtest-")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["LOAD_SAMPLE_DATA"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app import database
    from app.main import app

    database.init_db()
    # 每个测试使用干净的库
    with database.get_conn() as conn:
        conn.executescript(
            "DELETE FROM match_candidates; DELETE FROM match_results; "
            "DELETE FROM standard_addresses;")
    with TestClient(app) as c:
        yield c
