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
    #: Whether a finished build reaches the customer without a person seeing it.
    #:
    #: Off, and that is the default rather than the convenient value on purpose. The
    #: model can build a perfectly valid part that is not the part on the drawing;
    #: the shape claim catches a great deal of that and not all of it, and the
    #: difference between "a lot" and "all" is what an operator is for. Turning this
    #: on is a decision somebody makes about a service they already trust.
    automatic_acceptance: bool = False
    #: One machine, one person, no sign-in and no queue: upload a drawing, get files.
    #:
    #: Signing in, a CSRF token, an owner on every order and a person between a build
    #: and a download exist for a service strangers can reach. On a laptop with
    #: nobody else on it they are four ways to fail before the drawing is even read,
    #: and this setting turns all four off together.
    #:
    #: **It cannot be switched on outside `local`** — the validator below refuses to
    #: start rather than trusting anybody to remember. This is the one setting whose
    #: convenient value must never reach a deployment: with it on, every request is a
    #: signed-in customer and every build goes straight to whoever asks for it.
    #:
    #: It is off by default, which is the whole of its safety: a deployment that
    #: never sets it behaves exactly as it did before this existed.
    open_local_access: bool = False

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
        if self.open_local_access and self.environment.lower() != "local":
            # Refusing to start rather than starting with it quietly off. A service
            # configured to let anybody in is a service somebody *expects* to let
            # anybody in, and both ways that can happen — a mistake, or a deployment
            # that believes it is a laptop — are worth stopping for.
            raise ValueError("open_local_access is only allowed in the local environment")
        return self

    @property
    def hold_for_review(self) -> bool:
        """Whether a finished build waits for a person before the customer sees it.

        Open local access implies no hold. Holding a build for an operator who is the
        same person as the customer is a queue of one waiting for itself.
        """
        return not (self.automatic_acceptance or self.open_local_access)


settings = Settings()
