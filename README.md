# 地址匹配服务（Address Matcher）

把外部地址文本匹配到用户上传的标准地址表的本地 Web 应用：**FastAPI + SQLite**，零外部服务依赖。

- 归一化：Unicode NFKC（全角→半角）、大小写、常见道路/方位缩写（`St.→street`、`Ave→avenue`、`N→north`…）、门牌号格式（`No. 12` / `#12` / `12-A` / `12A` / `12号`）
- 双维相似度：**词元 F1**（含 difflib 模糊配对，容忍拼写差异）+ **门牌号相似度**（相等 1.0 / 主号相同 0.8 / 前缀 0.3 / 不同 0）
- 复核判定：最高分低于阈值、或前两名分差过小 → 标记**待确认**；低于下限 → 无匹配
- 可解释结果：展示**命中词元**、模糊配对、**冲突字段**（门牌号/城市/邮编不一致）、每个候选的分项得分
- 中文地址支持：CJK 二元组（bigram）词元化，命中词元自动并回原词展示
- 网页界面 + REST API，匹配结果持久化到 SQLite，支持人工确认 / 改选 / 判定无匹配

## 一键启动

```bash
docker compose up --build
```

打开 **http://localhost:8000** 即可使用网页界面；API 文档在 **http://localhost:8000/docs**。

首次启动会自动导入示例标准地址（`sample_data/standard_addresses.csv`，12 条中英混合数据），
可在「批量匹配」页下载示例外部地址 `external_addresses.csv` 直接上传体验完整流程。
不想自动导入示例数据：把 `docker-compose.yml` 里的 `LOAD_SAMPLE_DATA` 改为 `"0"`。

> 也可以不用 Compose：`docker build -t address-matcher . && docker run -p 8000:8000 -v $(pwd)/data:/app/data address-matcher`

### 本地开发（不用 Docker）

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# 运行测试：pip install pytest httpx && python -m pytest tests/ -q
```

## 使用流程

1. **标准地址表**页：上传标准地址 CSV（或逐条新增）。列：`id, address, city, state, postcode`
   （中文表头 `编号,地址,城市,省州,邮编` 同样识别；`id` 缺失时按行号生成）。
2. **单条匹配**页：粘贴一条外部地址，立即看到状态、候选列表、命中词元与冲突字段。
3. **批量匹配**页：上传外部地址 CSV（列：`id, address, city, state, postcode`），批量产出结果。
4. **复核队列**页：处理「待确认」——确认首选、改选其他候选、或判定无匹配。

## 匹配模型

```
score = 0.68 × token_similarity + 0.32 × number_similarity
```

| 判定 | 条件（默认值，可用环境变量覆盖） |
|---|---|
| 自动匹配 `auto_matched` | 最高分 ≥ `MATCH_THRESHOLD`(0.80) 且与第二名分差 ≥ `MATCH_MARGIN`(0.05) |
| 待确认 `needs_review` | 最高分 < 0.80，或前两名分差 < 0.05 |
| 无匹配 `no_match` | 最高分 < `MATCH_FLOOR`(0.30) |

门牌号相似度：完全相等 1.0；主号相同仅后缀不同（`12A` vs `12B`）0.8；互为前缀（`12` vs `125`）0.3；
其余 0；任一方缺失按中性 0.5 计。词元相似度为多重集 F1：先精确命中，剩余词元按
difflib 比率 ≥ 0.82 贪心模糊配对（每对计 0.5 次命中）。

## REST API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/config` | 当前阈值配置 |
| POST | `/api/standard-addresses/upload` | 上传标准地址 CSV（按 `id` upsert） |
| POST | `/api/standard-addresses` | 新增/更新单条标准地址 |
| GET | `/api/standard-addresses?limit=&offset=&q=` | 列表 / 搜索 |
| DELETE | `/api/standard-addresses/{id}` | 删除 |
| POST | `/api/match` | 单条匹配（可带 `city/state/postcode/threshold/margin/persist`） |
| POST | `/api/match/batch` | JSON 数组批量匹配 |
| POST | `/api/match/upload` | 上传外部地址 CSV 批量匹配 |
| GET | `/api/match-results?status=&reviewed=` | 匹配结果列表（可按状态过滤） |
| GET | `/api/match-results/{id}` | 结果详情（含全部候选） |
| POST | `/api/match-results/{id}/review` | 复核：`confirm` / `choose`（带 `standard_id`）/ `reject` |
| GET | `/api/stats` | 统计汇总 |

### 示例

```bash
# 上传标准地址表
curl -F "file=@sample_data/standard_addresses.csv" http://localhost:8000/api/standard-addresses/upload

# 单条匹配
curl -X POST http://localhost:8000/api/match \
  -H 'Content-Type: application/json' \
  -d '{"address": "123 MAIN ST., apt 4b", "city": "Springfield", "state": "IL", "postcode": "62701"}'

# 批量匹配（上传外部地址 CSV）
curl -F "file=@sample_data/external_addresses.csv" http://localhost:8000/api/match/upload

# 查看待确认并复核
curl "http://localhost:8000/api/match-results?status=needs_review"
curl -X POST http://localhost:8000/api/match-results/3/review \
  -H 'Content-Type: application/json' -d '{"action": "confirm"}'
```

响应中的每个候选包含：`score`（综合分）、`token_score` / `number_score`（分项）、
`matched_tokens`（命中词元）、`fuzzy_pairs`（模糊配对）、`conflicts`（冲突字段）。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DB_PATH` | `./data/addresses.db` | SQLite 文件路径（容器内 `/app/data/addresses.db`） |
| `MATCH_THRESHOLD` | `0.80` | 自动匹配最低分 |
| `MATCH_MARGIN` | `0.05` | 前两名最小分差 |
| `MATCH_FLOOR` | `0.30` | 无匹配下限 |
| `TOP_K` | `5` | 每条地址保留的候选数 |
| `TOKEN_WEIGHT` | `0.68` | 词元相似度权重（门牌号权重 = 1 − 该值） |
| `LOAD_SAMPLE_DATA` | `0`（compose 中为 `1`） | 首次启动自动导入示例标准地址 |

## 项目结构

```
app/
  main.py       FastAPI 路由（网页 + REST API）
  normalize.py  归一化：Unicode/大小写/缩写/门牌号/中英文词元化
  matching.py   相似度计算、候选评分、复核判定
  services.py   CSV 解析、标准库装载、匹配编排
  database.py   SQLite 数据访问（标准库 / 匹配结果 / 复核）
  static/       网页界面（原生 JS 单页）
sample_data/    示例标准地址表与外部地址（中英混合）
tests/          pytest：归一化 / 匹配引擎 / API 端到端（33 例）
Dockerfile / docker-compose.yml
```

数据持久化：SQLite 文件落在 `./data/`（compose 已挂载卷），删除该目录即重置。
