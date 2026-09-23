"""API 请求/响应模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class MatchRequest(BaseModel):
    address: str = Field(..., description="待匹配的外部地址文本")
    city: str = Field("", description="可选：城市（用于冲突检测）")
    state: str = Field("", description="可选：州/省")
    postcode: str = Field("", description="可选：邮编")
    threshold: float | None = Field(None, description="可选：覆盖自动匹配阈值")
    margin: float | None = Field(None, description="可选：覆盖最小分差")
    persist: bool = Field(True, description="是否把结果写入复核列表")


class BatchMatchRequest(BaseModel):
    addresses: list[str] = Field(..., min_length=1, description="地址文本列表")
    persist: bool = True


class ReviewRequest(BaseModel):
    action: str = Field(..., description="confirm=确认首条 / choose=选定候选 / reject=判定无匹配")
    standard_id: int | None = Field(None, description="action=choose 时必填：选定的标准地址 id")
    note: str = ""


class StandardAddressIn(BaseModel):
    ext_id: str = Field(..., description="外部编号（唯一）")
    address: str
    city: str = ""
    state: str = ""
    postcode: str = ""
