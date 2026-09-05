# encoding: utf-8
# @file: models.py
# @desc: 电线电缆物料条目结构化模型与字段映射
from typing import List, Optional, Union

from pydantic import BaseModel, Field


class CableItem(BaseModel):
    """电线电缆物料条目（英文字段用于 LLM 结构化输出，返回结果映射为中文字段名）"""
    model: Optional[str] = Field(default=None, description="产品型号，如 YJV、BV、RVV、WDZ-YJY 等")
    spec: Optional[str] = Field(default=None, description="规格，如 3x2.5mm²、1x16 等（芯数x截面积）")
    voltage: Optional[str] = Field(default=None, description="额定电压等级，如 0.6/1kV、450/750V 等")
    color: Optional[str] = Field(default=None, description="颜色，如 红、黄、蓝、绿、黑、白等")
    standard: Optional[str] = Field(default=None, description="执行标准编号，如 GB/T 5023、JB/T 8734 等")
    quantity: Optional[Union[int, float, str]] = Field(default=None, description="数量，输出为数字；无法确定时输出原文")
    unit: Optional[str] = Field(default=None, description="计量单位，如 米、盘、卷、千米 等")


class CableItemList(BaseModel):
    """物料条目列表"""
    items: List[CableItem] = Field(default_factory=list, description="从文档中提取的全部物料条目")


# LLM 输出字段 -> 中文字段 映射
FIELD_MAP = {
    "model": "型号",
    "spec": "规格",
    "voltage": "电压",
    "color": "颜色",
    "standard": "标准",
    "quantity": "数量",
    "unit": "单位",
}

# 中文目标字段列表
FIELDS_CN = list(FIELD_MAP.values())
