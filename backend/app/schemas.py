from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Money = Annotated[Decimal, Field(ge=0, le=1_000_000, decimal_places=6)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(StrictModel):
    user_id: str


class AssetCreate(StrictModel):
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10, max_length=2000)
    kind: Literal["agent", "mcp", "skill"]
    team_id: str | None = None
    department_id: str
    visibility: Literal["private", "team", "global"] = "team"
    endpoint: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=5)
    budget: Money = Decimal(100)

    @model_validator(mode="after")
    def personal_visibility(self):
        if self.visibility == "private" and self.team_id:
            raise ValueError("Private visibility requires personal ownership, without a team")
        return self

    @field_validator("endpoint")
    @classmethod
    def endpoint_scheme(cls, value):
        if value and not value.startswith(("https://", "http://localhost")):
            raise ValueError("Use an HTTPS endpoint or localhost for development")
        return value

    @field_validator("tags")
    @classmethod
    def tag_length(cls, value):
        if any(not tag or len(tag) > 32 for tag in value):
            raise ValueError("Tags must contain 1–32 characters")
        return value


class AssetEdit(StrictModel):
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10, max_length=2000)
    endpoint: str = Field(default="", max_length=500)
    version: int = Field(ge=1)

    _endpoint_scheme = field_validator("endpoint")(AssetCreate.endpoint_scheme.__func__)


class BudgetChange(StrictModel):
    amount: Money
    reason: str = Field(min_length=5, max_length=1000)


class KeyRequest(StrictModel):
    asset_id: str
    name: str = Field(min_length=3, max_length=120)
    budget: Money
    rpm: int = Field(default=30, ge=1, le=600)
    tpm: int = Field(default=20000, ge=256, le=1_000_000)
    days: int = Field(default=30, ge=1, le=90)
    reason: str = Field(min_length=5, max_length=1000)


class Decision(StrictModel):
    decision: Literal["approve", "decline"]
    note: str = Field(min_length=5, max_length=1000)
    budget: Money | None = None
    rpm: int | None = Field(default=None, ge=1, le=600)
    tpm: int | None = Field(default=None, ge=256, le=1_000_000)


class Delegation(StrictModel):
    user_id: str
    grant: bool


class DepartmentCreate(StrictModel):
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=500)


class AdminAssignment(StrictModel):
    user_id: str
    grant: bool = True


class Message(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=16000)


class Completion(StrictModel):
    model: Literal["governed-demo", "governed-premium"]
    messages: list[Message] = Field(min_length=1, max_length=32)
    max_tokens: int = Field(ge=1, le=2048)
    stream: Literal[False] = False
    # How sensitive the prompt is. LiteLLM's Cerbos guard uses it to decide which models
    # may receive it (cerbos/policies/model.yaml).
    data_classification: Literal["public", "internal", "confidential"] = "internal"

    def litellm_body(self):
        """The OpenAI-compatible body LiteLLM receives; the classification travels as metadata."""
        body = self.model_dump(exclude={"data_classification"})
        body["metadata"] = {"data_classification": self.data_classification}
        return body
