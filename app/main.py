"""FastAPI 入口：网页界面 + REST API。

启动：uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, database, services
from .normalize import normalize_address
from .schemas import BatchMatchRequest, MatchRequest, ReviewRequest, StandardAddressIn


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    # 可选：首次启动自动导入示例标准地址
    if config.LOAD_SAMPLE_DATA and database.count_standards() == 0 \
            and config.SAMPLE_DATA_PATH.exists():
        rows = services.parse_csv(config.SAMPLE_DATA_PATH.read_bytes())
        services.import_standards(rows)
    yield


app = FastAPI(
    title="地址匹配服务 Address Matcher",
    description="把外部地址文本匹配到标准地址表：归一化 + 词元/门牌号双维相似度 + 人工复核。",
    version="1.0.0",
    lifespan=lifespan,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "standard_count": database.count_standards()}


@app.get("/api/config")
def get_config() -> dict:
    return {
        "match_threshold": config.MATCH_THRESHOLD,
        "match_margin": config.MATCH_MARGIN,
        "match_floor": config.MATCH_FLOOR,
        "top_k": config.TOP_K,
        "token_weight": config.TOKEN_WEIGHT,
        "number_weight": config.NUMBER_WEIGHT,
        "fuzzy_token_ratio": config.FUZZY_TOKEN_RATIO,
    }


# ---------------------------------------------------------------------------
# 标准地址表
# ---------------------------------------------------------------------------

@app.post("/api/standard-addresses/upload")
async def upload_standards(file: UploadFile = File(..., description="标准地址 CSV 文件")) -> dict:
    content = await file.read()
    try:
        rows = services.parse_csv(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return services.import_standards(rows)


@app.post("/api/standard-addresses")
def add_standard(item: StandardAddressIn) -> dict:
    norm = normalize_address(" ".join(p for p in
                                      [item.address, item.city, item.state, item.postcode] if p))
    std_id = database.upsert_standard(item.ext_id, item.address, item.city,
                                      item.state, item.postcode, norm)
    return {"id": std_id}


@app.get("/api/standard-addresses")
def get_standards(limit: int = Query(100, le=500), offset: int = 0, q: str = "") -> dict:
    return database.list_standards(limit, offset, q)


@app.delete("/api/standard-addresses/{std_id}")
def remove_standard(std_id: int) -> dict:
    if not database.delete_standard(std_id):
        raise HTTPException(404, "标准地址不存在")
    return {"deleted": std_id}


# ---------------------------------------------------------------------------
# 匹配
# ---------------------------------------------------------------------------

@app.post("/api/match")
def match_one(req: MatchRequest) -> dict:
    if not req.address.strip():
        raise HTTPException(400, "address 不能为空")
    thresholds = {k: v for k, v in
                  {"threshold": req.threshold, "margin": req.margin}.items() if v is not None}
    return services.run_match(
        req.address,
        fields={"city": req.city, "state": req.state, "postcode": req.postcode},
        persist=req.persist, **thresholds)


@app.post("/api/match/batch")
def match_batch(req: BatchMatchRequest) -> dict:
    standards = services.load_standards()
    results = [services.run_match(a, standards=standards, persist=req.persist)
               for a in req.addresses if a.strip()]
    return {"count": len(results), "results": results}


@app.post("/api/match/upload")
async def match_upload(file: UploadFile = File(..., description="外部地址 CSV 文件")) -> dict:
    content = await file.read()
    try:
        rows = services.parse_csv(content, external=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    standards = services.load_standards()
    results = [services.run_match(
        row["address"], standards=standards, persist=True, source_id=row["id"],
        fields={"city": row["city"], "state": row["state"], "postcode": row["postcode"]})
        for row in rows]
    summary = {"auto_matched": 0, "needs_review": 0, "no_match": 0}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {"count": len(results), "summary": summary, "results": results}


# ---------------------------------------------------------------------------
# 复核
# ---------------------------------------------------------------------------

@app.get("/api/match-results")
def get_results(status: str = "", reviewed: bool | None = None,
                limit: int = Query(50, le=200), offset: int = 0) -> dict:
    flag = None if reviewed is None else int(reviewed)
    return database.list_results(status=status, reviewed=flag, limit=limit, offset=offset)


@app.get("/api/match-results/{result_id}")
def get_result(result_id: int) -> dict:
    d = database.get_result(result_id)
    if d is None:
        raise HTTPException(404, "匹配结果不存在")
    return d


@app.post("/api/match-results/{result_id}/review")
def review_result(result_id: int, req: ReviewRequest) -> dict:
    if req.action not in ("confirm", "choose", "reject"):
        raise HTTPException(400, "action 必须是 confirm / choose / reject")
    if req.action == "choose" and req.standard_id is None:
        raise HTTPException(400, "action=choose 时必须提供 standard_id")
    if database.get_result(result_id) is None:
        raise HTTPException(404, "匹配结果不存在")
    database.review_result(result_id, req.action, req.standard_id, req.note)
    return database.get_result(result_id)


@app.get("/api/stats")
def stats() -> dict:
    return database.stats()


# ---------------------------------------------------------------------------
# 网页
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 示例数据可直接下载（网页上的下载链接）
app.mount("/sample_data",
          StaticFiles(directory=config.BASE_DIR / "sample_data"),
          name="sample_data")
