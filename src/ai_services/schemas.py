"""Request, response and error models. Constraints mirror data-model.md and the OpenAPI contract."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_services.errors import ErrorCode

IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9._:@-]{1,128}")
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{8,128}")

MAX_CONTENT_CHARS = 32000
MAX_MESSAGES = 100


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[Message] = Field(
        min_length=1,
        max_length=MAX_MESSAGES,
        description="Full ordered history; the last message has role user.",
    )

    @model_validator(mode="after")
    def _last_message_is_user(self) -> "ChatRequest":
        if self.messages[-1].role != "user":
            raise ValueError("the last message must have role 'user'")
        return self


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    request_id: str
    details: dict[str, object] | None = None
    retry_after_seconds: int | None = Field(default=None, ge=0)


class Error(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail


class Liveness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


class DependencyStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["up", "down"]


class Readiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "not_ready"]
    dependencies: list[DependencyStatus] | None = Field(
        default=None, description="Present only for callers with the service credential."
    )


class ContractInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
