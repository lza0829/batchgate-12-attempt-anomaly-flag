from pydantic import BaseModel, Field, model_validator

from app.engines.anomaly import POLICIES


class MaxAttemptsBody(BaseModel):
    max_attempts: int = Field(ge=1, le=10)


class BaselineBody(BaseModel):
    row_min: int | None = Field(default=None, ge=0)
    row_max: int | None = Field(default=None, ge=0)
    anomaly_policy: str = Field(default="alert")

    @model_validator(mode="after")
    def _check(self):
        if self.anomaly_policy not in POLICIES:
            raise ValueError(f"anomaly_policy must be one of {', '.join(POLICIES)}")
        if (self.row_min is None) != (self.row_max is None):
            raise ValueError("row_min and row_max must be set or cleared together")
        if self.row_min is not None and self.row_min > self.row_max:
            raise ValueError("row_min must not exceed row_max")
        return self
