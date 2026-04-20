from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints


UserId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RequestBody(BaseModel):
    user_id: UserId
    payload: Any = None


class RequestResponse(BaseModel):
    status: Literal["ok"]
    reset_in_seconds: int | None = None
    requests_left_in_window: int | None = None


class UserStats(BaseModel):
    total_requests: int = Field(ge=0)
    requests_in_current_window: int = Field(ge=0)
    remaining_quota: int = Field(ge=0)
    window_reset_in_seconds: int = Field(ge=0)
    last_request_ts: int = Field(ge=0)


class StatsResponse(BaseModel):
    users: dict[str, UserStats]
