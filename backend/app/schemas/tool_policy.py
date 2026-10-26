from pydantic import BaseModel, Field


class ToolPolicyRead(BaseModel):
    name: str
    description: str | None
    risk_level: int


class ToolPolicyUpdate(BaseModel):
    risk_level: int = Field(ge=0, le=3)
