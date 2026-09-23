"""相似度计算与匹配引擎。

评分模型：
    score = TOKEN_WEIGHT * token_similarity + NUMBER_WEIGHT * number_similarity

- token_similarity：词元多重集的 F1（先精确命中，剩余词元再做 difflib 模糊配对）
- number_similarity：门牌号单独比对（完全相等 1.0，主号相同 0.8，前缀 0.3，否则 0）

复核判定：
- 最高分 < MATCH_THRESHOLD            -> 待确认（分数不足）
- 前两名分差 < MATCH_MARGIN           -> 待确认（候选过于接近）
- 最高分 < MATCH_FLOOR                -> 无匹配
"""
from __future__ import annotations

import difflib
from collections import Counter
from dataclasses import dataclass, field

from . import config
from .normalize import NormalizedAddress, merge_cjk_bigrams


@dataclass
class StandardRecord:
    """标准地址表中的一条记录（内存表示）。"""
    id: int
    ext_id: str
    raw_text: str
    city: str = ""
    state: str = ""
    postcode: str = ""
    norm: NormalizedAddress | None = None


@dataclass
class CandidateScore:
    """一个候选标准地址的评分与可解释信息。"""
    standard_id: int
    ext_id: str
    std_text: str
    std_city: str = ""
    std_state: str = ""
    std_postcode: str = ""
    std_house_number: str | None = None
    score: float = 0.0
    token_score: float = 0.0
    number_score: float = 0.0
    matched_tokens: list[str] = field(default_factory=list)
    fuzzy_pairs: list[list[str]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "standard_id": self.standard_id,
            "ext_id": self.ext_id,
            "std_text": self.std_text,
            "std_city": self.std_city,
            "std_state": self.std_state,
            "std_postcode": self.std_postcode,
            "std_house_number": self.std_house_number,
            "score": round(self.score, 4),
            "token_score": round(self.token_score, 4),
            "number_score": round(self.number_score, 4),
            "matched_tokens": self.matched_tokens,
            "fuzzy_pairs": self.fuzzy_pairs,
            "conflicts": self.conflicts,
        }


# ---------------------------------------------------------------------------
# 词元相似度
# ---------------------------------------------------------------------------

def token_similarity(a_tokens: list[str], b_tokens: list[str],
                     fuzzy_ratio: float = config.FUZZY_TOKEN_RATIO
                     ) -> tuple[float, list[str], list[list[str]]]:
    """词元多重集 F1。返回 (分数, 精确命中词元, 模糊配对[[a,b],...])。

    先按多重集精确匹配；两边剩余词元用 difflib 比率 >= fuzzy_ratio 贪心配对，
    每对按 0.5 次命中计（容忍拼写差异但不等同完全命中）。
    """
    if not a_tokens or not b_tokens:
        return 0.0, [], []

    ca, cb = Counter(a_tokens), Counter(b_tokens)
    exact_keys = list((ca & cb).elements())
    exact_hits = len(exact_keys)

    rem_a = list((ca - cb).elements())
    rem_b = list((cb - ca).elements())

    # 贪心模糊配对：枚举所有候选对，按相似度从高到低消耗
    pairs: list[tuple[float, int, int]] = []
    for i, ta in enumerate(rem_a):
        for j, tb in enumerate(rem_b):
            r = difflib.SequenceMatcher(None, ta, tb).ratio()
            if r >= fuzzy_ratio:
                pairs.append((r, i, j))
    pairs.sort(reverse=True)

    used_a: set[int] = set()
    used_b: set[int] = set()
    fuzzy_pairs: list[list[str]] = []
    fuzzy_hits = 0.0
    for r, i, j in pairs:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        fuzzy_pairs.append([rem_a[i], rem_b[j]])
        fuzzy_hits += 0.5

    hits = exact_hits + fuzzy_hits
    precision = hits / len(a_tokens)
    recall = hits / len(b_tokens)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return f1, exact_keys, fuzzy_pairs


# ---------------------------------------------------------------------------
# 门牌号相似度
# ---------------------------------------------------------------------------

def house_number_similarity(a: str | None, b: str | None) -> float:
    """门牌号相似度：相等 1.0；主号相同（12 vs 12a）0.8；前缀相关 0.3；否则 0。
    任一方缺失返回中性分 MISSING_NUMBER_SIM。"""
    if not a or not b:
        return config.MISSING_NUMBER_SIM
    if a == b:
        return 1.0
    main_a = a.split("-")[0].split("/")[0].rstrip("abcdefghijklmnopqrstuvwxyz")
    main_b = b.split("-")[0].split("/")[0].rstrip("abcdefghijklmnopqrstuvwxyz")
    if main_a and main_a == main_b:
        return 0.8
    if a.startswith(b) or b.startswith(a):
        return 0.3
    return 0.0


# ---------------------------------------------------------------------------
# 字段冲突
# ---------------------------------------------------------------------------

def _norm_field(s: str) -> str:
    from .normalize import basic_normalize
    return basic_normalize(s).replace(" ", "")


def find_conflicts(query_norm: NormalizedAddress, std: StandardRecord,
                   query_fields: dict | None = None) -> list[str]:
    """生成人可读的冲突字段列表（不直接扣分，供人工复核参考）。"""
    conflicts: list[str] = []
    qn, sn = query_norm.house_number, (std.norm.house_number if std.norm else None)
    if qn and sn and qn != sn:
        conflicts.append(f"门牌号不一致: 输入 {qn} / 标准 {sn}")
    elif qn and not sn:
        conflicts.append(f"标准地址缺少门牌号（输入为 {qn}）")
    elif sn and not qn:
        conflicts.append(f"输入地址缺少门牌号（标准为 {sn}）")

    q_postcode = (query_fields or {}).get("postcode", "")
    if q_postcode and std.postcode and _norm_field(q_postcode) != _norm_field(std.postcode):
        conflicts.append(f"邮编不一致: 输入 {q_postcode} / 标准 {std.postcode}")
    q_city = (query_fields or {}).get("city", "")
    if q_city and std.city and _norm_field(q_city) != _norm_field(std.city):
        conflicts.append(f"城市不一致: 输入 {q_city} / 标准 {std.city}")
    q_state = (query_fields or {}).get("state", "")
    if q_state and std.state and _norm_field(q_state) != _norm_field(std.state):
        conflicts.append(f"州/省不一致: 输入 {q_state} / 标准 {std.state}")
    return conflicts


# ---------------------------------------------------------------------------
# 匹配主流程
# ---------------------------------------------------------------------------

def score_candidate(query_norm: NormalizedAddress, std: StandardRecord,
                    query_fields: dict | None = None) -> CandidateScore:
    std_tokens = std.norm.tokens if std.norm else []
    token_score, matched, fuzzy = token_similarity(query_norm.tokens, std_tokens)
    number_score = house_number_similarity(query_norm.house_number,
                                           std.norm.house_number if std.norm else None)
    score = config.TOKEN_WEIGHT * token_score + config.NUMBER_WEIGHT * number_score
    # 命中词元按标准地址中的出现顺序排列，便于 CJK 二元组并回原词展示
    matched_set = set(matched)
    seen: set[str] = set()
    ordered = [t for t in std_tokens
               if t in matched_set and not (t in seen or seen.add(t))]
    return CandidateScore(
        standard_id=std.id,
        ext_id=std.ext_id,
        std_text=std.raw_text,
        std_city=std.city,
        std_state=std.state,
        std_postcode=std.postcode,
        std_house_number=std.norm.house_number if std.norm else None,
        score=score,
        token_score=token_score,
        number_score=number_score,
        matched_tokens=merge_cjk_bigrams(ordered),
        fuzzy_pairs=[[merge_cjk_bigrams([p[0]])[0], merge_cjk_bigrams([p[1]])[0]] for p in fuzzy],
        conflicts=find_conflicts(query_norm, std, query_fields),
    )


def match_address(query_norm: NormalizedAddress,
                  standards: list[StandardRecord],
                  query_fields: dict | None = None,
                  threshold: float | None = None,
                  margin: float | None = None,
                  floor: float | None = None,
                  top_k: int | None = None) -> dict:
    """对单条地址在标准库中匹配，返回状态 + 候选列表 + 复核原因。"""
    threshold = config.MATCH_THRESHOLD if threshold is None else threshold
    margin = config.MATCH_MARGIN if margin is None else margin
    floor = config.MATCH_FLOOR if floor is None else floor
    top_k = config.TOP_K if top_k is None else top_k

    scored = [score_candidate(query_norm, std, query_fields) for std in standards]
    scored.sort(key=lambda c: c.score, reverse=True)
    top = scored[:top_k]

    reasons: list[str] = []
    if not top or top[0].score < floor:
        status = "no_match"
        reasons.append(f"最高分 {top[0].score:.2f} 低于无匹配下限 {floor:.2f}" if top
                       else "标准地址库为空")
    else:
        best = top[0].score
        second = top[1].score if len(top) > 1 else 0.0
        if best < threshold:
            reasons.append(f"最高分 {best:.2f} 低于自动匹配阈值 {threshold:.2f}")
        if best - second < margin:
            reasons.append(f"前两名分差 {best - second:.2f} 小于最小分差 {margin:.2f}，候选过于接近")
        status = "needs_review" if reasons else "auto_matched"

    return {
        "status": status,
        "reasons": reasons,
        "best_candidate": top[0] if top and status != "no_match" else None,
        "candidates": top,
    }
