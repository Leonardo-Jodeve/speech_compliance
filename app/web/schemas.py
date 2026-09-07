"""管理台输入白名单；业务 ID 始终为字符串。"""
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
BusinessId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Weight = Annotated[float, Field(ge=0, le=999.99, allow_inf_nan=False)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SceneInput(InputModel):
    source_scene_id: BusinessId
    scene_name: Name
    description: str = Field(default="", max_length=10000)
    enabled: bool = True


class RuleInput(InputModel):
    rule_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    rule_name: Name
    rule_type: Literal["REQUIRED", "FORBIDDEN", "CONDITIONAL_REQUIRED"] = "REQUIRED"
    description: str = Field(default="", max_length=20000)
    standard_expression: str = Field(default="", max_length=20000)
    judge_instruction: str = Field(default="", max_length=20000)
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = "MEDIUM"
    weight: Weight = 10
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def valid_dates(self):
        # 浏览器 datetime-local 与源业务时间均按 UTC+8 解释。
        for name in ("effective_from", "effective_to"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                setattr(self, name, value.replace(tzinfo=timezone(timedelta(hours=8))))
        if self.effective_from and self.effective_to and self.effective_from >= self.effective_to:
            raise ValueError("生效结束时间必须晚于开始时间")
        return self


class BindingInput(InputModel):
    scene_id: int = Field(gt=0)
    rule_id: int = Field(gt=0)
    enabled: bool = True
    weight_override: Weight | None = None


class RunInput(InputModel):
    search_id: str = Field(min_length=1, max_length=64)
    call_keys: list[str] = Field(min_length=1, max_length=100)


MODELS = {"scenes": SceneInput, "rules": RuleInput, "bindings": BindingInput}
