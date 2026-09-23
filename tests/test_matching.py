"""评分与匹配引擎测试（含示例数据的端到端期望）。"""
from app.matching import (StandardRecord, house_number_similarity,
                          match_address)
from app.normalize import normalize_address


def _std(ext_id, text, **kw) -> StandardRecord:
    return StandardRecord(id=hash(ext_id) & 0xffff, ext_id=ext_id, raw_text=text,
                          norm=normalize_address(text), **kw)


def test_house_number_similarity():
    assert house_number_similarity("12", "12") == 1.0
    assert house_number_similarity("12a", "12b") == 0.8       # 主号相同
    assert house_number_similarity("12", "125") == 0.3       # 一个是另一个的前缀
    assert house_number_similarity("123", "125") == 0.0      # 都不同前缀
    assert house_number_similarity("12", "99") == 0.0
    assert house_number_similarity(None, "12") == 0.5        # 缺失 -> 中性


def test_abbrev_variants_match_high():
    stds = [_std("STD-001", "123 Main Street Apt 4B")]
    r = match_address(normalize_address("123 MAIN ST., apt 4b"), stds)
    assert r["status"] == "auto_matched"
    assert r["best_candidate"].ext_id == "STD-001"
    assert r["best_candidate"].score > 0.95


def test_wrong_house_number_lowers_score_and_flags_review():
    stds = [_std("STD-001", "123 Main Street Apt 4B")]
    r = match_address(normalize_address("125 Main Street Apt 4B"), stds)
    assert r["status"] == "needs_review"
    assert any("阈值" in x for x in r["reasons"])
    # 词元几乎全中，但门牌号完全错误 -> number=0，综合分被拉到阈值以下
    assert r["best_candidate"].token_score > 0.9
    assert r["best_candidate"].number_score == 0.0
    assert any("门牌号不一致" in c for c in r["best_candidate"].conflicts)


def test_house_number_letter_suffix_mismatch_is_soft():
    # 主号相同仅后缀不同（12A vs 12B）-> 0.8，不应直接打回
    stds = [_std("STD-001", "123 Main Street")]
    r = match_address(normalize_address("123a Main Street"), stds)
    assert r["best_candidate"].number_score == 0.8


def test_missing_number_on_input_still_matchable():
    stds = [_std("STD-002", "123 Main Street Ste 9")]
    r = match_address(normalize_address("123 Main"), stds)
    # 词元部分缺失（少了 street / unit / 9），分差无第二候选 -> 看绝对分
    assert r["best_candidate"].ext_id == "STD-002"


def test_ambiguous_two_candidates_small_margin():
    # 同一门牌同一街道、仅单元号不同的两条标准地址：缺单元号时二者同分 -> 分差过小
    stds = [
        _std("STD-001", "123 Main Street Apt 4B"),
        _std("STD-002", "123 Main Street Ste 9"),
    ]
    r = match_address(normalize_address("123 Main Street"), stds)
    assert r["status"] == "needs_review"
    assert any("分差" in x for x in r["reasons"])
    assert len(r["candidates"]) >= 2


def test_chinese_good_match():
    stds = [
        _std("STD-009", "10 世纪大道 88 号 金茂大厦"),
        _std("STD-011", "88 南京路 365 号"),
    ]
    r = match_address(normalize_address("世纪大道88号金茂大厦"), stds)
    assert r["best_candidate"].ext_id == "STD-009"
    assert r["status"] == "auto_matched"


def test_completely_unrelated_is_no_match():
    stds = [_std("STD-003", "450 Oak Avenue")]
    r = match_address(normalize_address("742 Evergreen Terrace"), stds)
    assert r["status"] == "no_match"


def test_matched_tokens_are_reported():
    stds = [_std("STD-006", "789 Elm Boulevard Apt 12")]
    r = match_address(normalize_address("789 Elm Blvd #12"), stds)
    # 789 作为门牌号单独比对，#12 等价于 unit 12 参与词元匹配
    matched = set(r["best_candidate"].matched_tokens)
    assert {"elm", "boulevard", "unit", "12"} <= matched
    assert r["best_candidate"].std_house_number == "789"


def test_city_conflict_reported():
    stds = [_std("STD-003", "450 Oak Avenue", city="Springfield", postcode="62702")]
    r = match_address(
        normalize_address("450 Oak Avenue Chicago 60607"),
        stds, query_fields={"city": "Chicago", "postcode": "60607"})
    conflicts = " ".join(r["best_candidate"].conflicts)
    assert "城市不一致" in conflicts
    assert "邮编不一致" in conflicts


def test_fuzzy_token_matches_typo():
    # Amphitheatre 长词的轻微拼写错误应通过模糊配对救回
    stds = [_std("STD-004", "1600 Amphitheatre Parkway")]
    r = match_address(normalize_address("1600 Amphitheater Pkwy"), stds)
    assert r["best_candidate"].fuzzy_pairs  # 至少存在模糊配对
    assert ["amphitheater", "amphitheatre"] in r["best_candidate"].fuzzy_pairs
    assert r["best_candidate"].token_score >= 0.7
    # 门牌号 + parkway 精确命中，综合分仍可自动匹配
    assert r["status"] == "auto_matched"


def test_empty_library():
    r = match_address(normalize_address("123 Main St"), [])
    assert r["status"] == "no_match"
