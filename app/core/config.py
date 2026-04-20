import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Settings:
    redis_url_override: Optional[str]
    redis_host: str
    redis_port: int
    redis_db: int
    max_requests: int
    window_seconds: int

    @property
    def redis_url(self) -> str:
        if self.redis_url_override:
            return self.redis_url_override
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


settings = Settings(
    redis_url_override=os.getenv("REDIS_URL"),
    redis_host=os.getenv("REDIS_HOST", "localhost"),
    redis_port=int(os.getenv("REDIS_PORT", "6379")),
    redis_db=int(os.getenv("REDIS_DB", "0")),
    max_requests=int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "5")),
    window_seconds=int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")),
)
