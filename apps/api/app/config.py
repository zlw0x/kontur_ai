from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    app_name: str = "cad-ai-api"
    environment: str = "local"
    database_url: str = "postgresql+psycopg://cad_ai:local-only-change-me@localhost:5432/cad_ai"
    redis_url: str = "redis://localhost:6379/0"
    worker_enrollment_token: str = "local-development-enrollment-token-change-me"
    manual_api_token: str = "local-development-manual-api-token-change-me"
    worker_repository_mode: Literal["sql", "memory"] = "sql"
    artifact_store_root: str = ".data/artifacts"
    max_artifact_bytes: int = 100 * 1024 * 1024
    web_origin: str = "http://localhost:3000"
    #: How often the reaper sweeps for jobs no worker will speak for again.
    #:
    #: Thirty seconds because the thing it ends is a customer looking at "waiting"
    #: — a minute of that is tolerable and an hour is not — and because a sweep
    #: that moves nothing is two indexed queries. Set to 0 to turn it off, which is
    #: what the tests do: they call `reap()` and assert, rather than waiting.
    reaper_interval_seconds: int = 30
    #: The image the sanitizer runs in. Empty means the child-process mode, which
    #: still has RLIMIT_AS, RLIMIT_CPU and a wall clock but shares the host's kernel
    #: namespace with the API. Production sets this; a laptop need not.
    sanitizer_image: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cookie_secure(self) -> bool:
        """Whether a session cookie is marked `Secure`, and so refused over plain HTTP.

        Derived rather than configured, because the one deployment where it must be
        off is the one where it can be recognised without asking: local development
        serves the API on `http://localhost`, and a `Secure` cookie there is simply
        never sent, which looks like sign-in silently not working.

        A setting would be a footgun with a default — the safe value breaks the
        laptop and the convenient value ships to production. This cannot be set to
        the wrong thing because it cannot be set at all.
        """
        return self.environment.lower() != "local"

    @model_validator(mode="after")
    def reject_development_secrets_outside_local(self):
        if self.environment.lower() != "local" and (
            self.worker_enrollment_token == "local-development-enrollment-token-change-me"
            or self.manual_api_token == "local-development-manual-api-token-change-me"
            or "local-only-change-me" in self.database_url
        ):
            raise ValueError("development credentials are forbidden outside the local environment")
        return self


settings = Settings()
