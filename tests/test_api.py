"""REST API 端到端测试。"""
import io

SAMPLE_STD = (
    "id,address,city,state,postcode\n"
    "STD-001,123 Main Street Apt 4B,Springfield,IL,62701\n"
    "STD-002,123 Main Street Ste 9,Springfield,IL,62701\n"
)


def _upload(client, csv_text, url="/api/standard-addresses/upload"):
    return client.post(url, files={"file": ("a.csv", io.BytesIO(csv_text.encode()),
                                            "text/csv")})


def test_health_and_config(client):
    assert client.get("/api/health").json()["status"] == "ok"
    cfg = client.get("/api/config").json()
    assert 0 < cfg["match_threshold"] < 1


def test_upload_standards_and_match(client):
    r = _upload(client, SAMPLE_STD)
    assert r.status_code == 200
    assert r.json()["total"] == 2

    r = client.post("/api/match", json={"address": "123 MAIN ST apt 4b",
                                        "city": "Springfield"})
    body = r.json()
    assert body["status"] == "auto_matched"
    assert body["best_candidate"]["ext_id"] == "STD-001"
    assert "123" not in body["tokens"]  # 123 是门牌号，单独抽取
    assert body["house_number"] == "123"
    assert "main" in body["best_candidate"]["matched_tokens"]
    assert body["id"]  # 已持久化


def test_match_no_persist(client):
    _upload(client, SAMPLE_STD)
    r = client.post("/api/match", json={"address": "123 Main St Apt 4B",
                                        "persist": False})
    assert r.status_code == 200
    assert "id" not in r.json()
    assert client.get("/api/match-results").json()["total"] == 0


def test_threshold_override(client):
    _upload(client, SAMPLE_STD)
    r = client.post("/api/match", json={"address": "123 Main",
                                        "threshold": 0.99})
    assert r.json()["status"] == "needs_review"


def test_batch_and_review_flow(client):
    _upload(client, SAMPLE_STD)
    r = client.post("/api/match/batch", json={"addresses": [
        "123 Main St Apt 4B", "125 Main Street"]})
    results = r.json()["results"]
    assert results[0]["status"] == "auto_matched"
    assert results[1]["status"] == "needs_review"

    rid = results[1]["id"]
    # 确认首选
    rr = client.post(f"/api/match-results/{rid}/review",
                     json={"action": "confirm"})
    assert rr.json()["status"] == "confirmed"
    assert rr.json()["reviewed"] == 1

    # 改选候选
    other_id = results[1]["candidates"][0]["standard_id"]
    rr = client.post(f"/api/match-results/{rid}/review",
                     json={"action": "choose", "standard_id": other_id,
                           "note": "门牌号录入有误"})
    assert rr.json()["status"] == "confirmed"

    # 判定无匹配
    rid2 = results[0]["id"]
    rr = client.post(f"/api/match-results/{rid2}/review",
                     json={"action": "reject"})
    assert rr.json()["status"] == "rejected"


def test_choose_requires_standard_id(client):
    _upload(client, SAMPLE_STD)
    rid = client.post("/api/match", json={"address": "123 Main St Apt 4B"}).json()["id"]
    r = client.post(f"/api/match-results/{rid}/review", json={"action": "choose"})
    assert r.status_code == 400


def test_upload_external_csv(client):
    _upload(client, SAMPLE_STD)
    ext = "id,address,city\nE1,123 main st apt 4b,Springfield\nE2,999 Nowhere Rd,Gotham\n"
    r = _upload(client, ext, url="/api/match/upload")
    body = r.json()
    assert body["count"] == 2
    assert body["summary"]["auto_matched"] == 1
    assert body["summary"]["no_match"] + body["summary"]["needs_review"] == 1


def test_upsert_and_list_delete(client):
    _upload(client, SAMPLE_STD)
    # 同 ext_id 再次上传 -> 更新而非新增
    r = _upload(client, "id,address\nSTD-001,999 Renewed Way\n")
    assert r.json()["imported"] == 0 and r.json()["updated"] == 1

    r = client.get("/api/standard-addresses?q=renewed")
    assert r.json()["total"] == 1
    sid = r.json()["items"][0]["id"]
    assert client.delete(f"/api/standard-addresses/{sid}").status_code == 200
    assert client.get("/api/standard-addresses?q=renewed").json()["total"] == 0


def test_bad_csv_returns_400(client):
    r = _upload(client, "foo,bar\n1,2\n")
    assert r.status_code == 400


def test_chinese_headers_and_html(client):
    r = _upload(client, "编号,地址,城市\nC-1,世纪大道88号,上海\n")
    assert r.status_code == 200
    r = client.post("/api/match", json={"address": "世纪大道88号"})
    assert r.json()["best_candidate"]["ext_id"] == "C-1"

    page = client.get("/")
    assert page.status_code == 200
    assert "地址匹配".encode() in page.content
