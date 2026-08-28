"""营销场景领域模型（手册 #6/#7/#15）。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketingScenario:
    """对应 qc_scene 表。

    source_scene_id 对应源表 act_scene_id，统一按字符串处理（手册 #7）。
    """

    id: int | None = None
    source_scene_id: str = ""
    scene_name: str = ""
    description: str | None = None
    enabled: bool = True

    @property
    def scene_id(self) -> str:
        return self.source_scene_id