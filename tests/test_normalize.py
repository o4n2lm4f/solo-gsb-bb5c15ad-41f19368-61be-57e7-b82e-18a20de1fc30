"""归一化测试：Unicode、大小写、缩写、门牌号、中文 bigram。"""
from app.normalize import merge_cjk_bigrams, normalize_address


def test_unicode_fullwidth_and_case():
    n = normalize_address("１２３ Ｍａｉｎ Ｓｔｒｅｅｔ")  # 全角拉丁字母
    assert n.house_number == "123"
    assert "main" in n.token_set
    assert "street" in n.token_set


def test_street_abbreviation():
    n = normalize_address("1600 Amphitheatre Pkwy")
    assert n.house_number == "1600"
    assert "parkway" in n.token_set
    assert "pkwy" not in n.token_set


def test_apartment_and_ste_normalize_to_unit():
    n1 = normalize_address("123 Main St Apt 4B")
    n2 = normalize_address("123 Main Street Ste 4B")
    assert n1.house_number == n2.house_number == "123"
    assert n1.token_set == n2.token_set
    assert "unit" in n1.token_set and "4b" in n1.token_set


def test_direction_abbreviation():
    n = normalize_address("500 N Michigan Ave")
    assert n.house_number == "500"
    assert {"north", "michigan", "avenue"} <= n.token_set


def test_hash_number_markers():
    # 句首的 # / No. 是门牌号
    assert normalize_address("#12 Main St").house_number == "12"
    assert normalize_address("No. 12 Main Street").house_number == "12"
    # 句中 #12 / No.12 是单元号：门牌号仍是开头数字，12 作为词元保留
    n = normalize_address("789 Elm Blvd #12")
    assert n.house_number == "789"
    assert "12" in n.token_set and "unit" in n.token_set
    n = normalize_address("789 Elm Boulevard no 12")
    assert n.house_number == "789"
    assert "12" in n.token_set and "unit" in n.token_set


def test_leading_house_number_with_suffix():
    n = normalize_address("221B Baker Street")
    assert n.house_number == "221b"
    assert {"baker", "street"} <= n.token_set


def test_number_hyphen_letter_collapsed():
    assert normalize_address("12-A Main St").house_number == "12a"
    assert normalize_address("1600-5 Amphitheatre Pkwy").house_number == "1600-5"


def test_chinese_address_bigrams_and_haoma():
    n = normalize_address("世纪大道88号金茂大厦")
    assert n.house_number == "88"
    # bigram: 世纪 纪大 大道 / 金茂 茂大 大厦
    assert {"世纪", "纪大", "大道", "金茂", "茂大", "大厦"} <= n.token_set


def test_chinese_fullwidth_numbers():
    # NFKC 把全角数字 ８８ -> 88
    n = normalize_address("南京路８８号")
    assert n.house_number == "88"
    assert {"南京", "京路"} <= n.token_set


def test_merge_cjk_bigrams_display():
    assert merge_cjk_bigrams(["世纪", "纪大", "大道"]) == ["世纪大道"]
    assert merge_cjk_bigrams(["main", "金茂", "茂大", "大厦"]) == ["main", "金茂大厦"]
    assert merge_cjk_bigrams(["单"]) == ["单"]


def test_no_house_number():
    n = normalize_address("Main Street Springfield")
    assert n.house_number is None
    assert {"main", "street", "springfield"} <= n.token_set
