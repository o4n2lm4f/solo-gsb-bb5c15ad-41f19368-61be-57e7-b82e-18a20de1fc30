"""地址归一化与词元化。

统一处理：
- Unicode NFKC 兼容分解（全角 -> 半角、兼容字符归并）
- 大小写（casefold）
- 常见英文道路/方位缩写展开（st -> street、n -> north ...）
- 门牌号格式统一（No. 12 / #12 / 12-A / 12A / 12号 -> 规范形式）
- 中英文混合词元化（英文按词，中文按二元组 bigram）
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 缩写表
# ---------------------------------------------------------------------------

# 常见道路类型缩写 -> 全称（美式为主，兼顾英式）
STREET_ABBREV: dict[str, str] = {
    "st": "street", "ave": "avenue", "av": "avenue", "rd": "road",
    "blvd": "boulevard", "dr": "drive", "ln": "lane", "ct": "court",
    "cir": "circle", "pl": "place", "sq": "square", "ter": "terrace",
    "terr": "terrace", "hwy": "highway", "pkwy": "parkway",
    "aly": "alley", "xing": "crossing", "trl": "trail", "way": "way",
    "cres": "crescent", "rdg": "ridge", "apt": "unit", "ste": "unit",
    "fl": "floor", "rm": "room", "bldg": "building", "dept": "department",
    "mt": "mount", "ft": "fort", "jct": "junction",
}

# 方位缩写 -> 全称（仅独立成词时展开，避免误伤如 "st" 在 "st john" 中按道路展开的问题，
# 这里按常见地址习惯处理：道路缩写优先，方位其次）
DIRECTION_ABBREV: dict[str, str] = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
}

# 门牌号引导词：No. 12 / No 12 / number 12 -> #12（便于后续抽取）
_PRE_NUMBER_MARKER = re.compile(r"\b(?:no|num|number)\.?(?=\s*\d)")

# 门牌号抽取（按地址类型分别处理）：
# - 西式：开头的数字串是门牌号（"12A Main St"、"1600 Amphitheatre Pkwy"）
# - 中文：路/街/大道…后的 "数字号" 是门牌号（"世纪大道88号"）
# 显式标记 "#12 / No.12" 若出现在门牌号位置（句首）才算门牌号，
# 否则视为单元号（#12 / unit 12），仅删除引导符、数字保留为词元参与相似度。
RE_CJK_NUMBER = re.compile(r"(\d[\da-zA-Z]*(?:[-/][\da-zA-Z]+)*)\s*(?:号|號|弄|栋|棟|幢|院)")
RE_LEADING_NUMBER = re.compile(r"^[\s#]*(\d[\da-z]*(?:[-/][\da-z]+)*)\b", re.I)

# 词元切分：连续 ASCII 字母数字 或 连续 CJK 字符
_TOKEN_RE = re.compile(r"[a-z0-9]+|[一-鿿㐀-䶿]+")


@dataclass
class NormalizedAddress:
    """一条地址的归一化结果。"""
    raw: str
    text: str                      # 归一化后的纯文本（小写、缩写已展开、无标点）
    tokens: list[str]              # 词元（已剔除门牌号词元）
    token_set: set[str] = field(default_factory=set)
    house_number: str | None = None  # 规范门牌号，如 "12a"、"12-3"

    def __post_init__(self) -> None:
        self.token_set = set(self.tokens)


def basic_normalize(text: str) -> str:
    """Unicode NFKC + casefold + 压缩空白。不做缩写展开和标点删除。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = text.casefold()
    return " ".join(text.split())


def canonicalize_house_number(raw: str) -> str:
    """统一门牌号写法：去空白/点号，数字-字母间的连字符去掉（12-A -> 12a），
    数字-数字间的连字符保留（12-3 通常表示楼栋-单元，语义不同）。"""
    s = raw.strip().lower()
    s = re.sub(r"[\s.]+", "", s)
    s = re.sub(r"(?<=\d)-(?=[a-z])|(?<=[a-z])-(?=\d)", "", s)
    return s


def extract_house_number(text: str) -> tuple[str | None, str]:
    """从归一化文本中抽取门牌号，返回 (门牌号, 剩余文本)。

    规则：中文优先取“数字+号/弄/栋…”；其余取句首数字（含 # / No. 引导，
    如 "#12 Main St"）；句中 "#12 / No.12" 视为单元号，不作为门牌号。
    """
    m = RE_CJK_NUMBER.search(text)
    if m:
        return canonicalize_house_number(m.group(1)), (text[:m.start()] + " " + text[m.end():])
    m = RE_LEADING_NUMBER.match(text.lstrip())
    if m:
        rest = text.lstrip()[m.end():]
        return canonicalize_house_number(m.group(1)), rest
    return None, text


def _cjk_bigrams(run: str) -> list[str]:
    """中文等 CJK 连续串切为二元组（单字串保留单字），保证“金陵路/金陵东路”
    这类包含关系不会全额命中，同时“金陵”与“金凌”不致误配。"""
    if len(run) == 1:
        return [run]
    return [run[i:i + 2] for i in range(len(run) - 1)]


def tokenize(text: str) -> list[str]:
    """归一化文本 -> 词元列表。英文缩写在此展开。"""
    tokens: list[str] = []
    for chunk in _TOKEN_RE.findall(text):
        if chunk.isascii():
            expanded = STREET_ABBREV.get(chunk) or DIRECTION_ABBREV.get(chunk) or chunk
            tokens.append(expanded)
        else:
            tokens.extend(_cjk_bigrams(chunk))
    return tokens


def normalize_address(raw: str) -> NormalizedAddress:
    """完整归一化流程：NFKC/大小写 -> 门牌号引导词替换 -> 标点清理 ->
    门牌号抽取 -> 词元化。"""
    text = basic_normalize(raw)
    text = _PRE_NUMBER_MARKER.sub("#", text)
    # 标点统一为空格（连字符保留给门牌号抽取，抽取后剩余连字符已无意义，一并清掉）
    text = re.sub(r"[,，;；:：。\.、/\\()（）\[\]{}\"']", " ", text)
    house_number, text = extract_house_number(text)
    # 句中残留的 "#"（单元号标记，如 "Blvd #12"）等价于 unit，数字保留为词元
    text = text.replace("#", " unit ").replace("-", " ")
    text = " ".join(text.split())
    tokens = tokenize(text)
    return NormalizedAddress(raw=raw, text=text, tokens=tokens, house_number=house_number)


def merge_cjk_bigrams(tokens: list[str]) -> list[str]:
    """把可拼接的相邻 CJK 二元组并回原词，便于展示命中词元。
    如 ["金陵","陵路"] -> ["金陵路"]；无法拼接的原样保留。"""
    merged: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if len(tok) == 2 and not tok.isascii():
            run = tok
            j = i + 1
            while j < len(tokens) and len(tokens[j]) == 2 and not tokens[j].isascii() \
                    and tokens[j][0] == run[-1]:
                run += tokens[j][1]
                j += 1
            merged.append(run)
            i = j
        else:
            merged.append(tok)
            i += 1
    return merged
