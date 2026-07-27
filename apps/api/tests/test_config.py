import pytest
from pydantic import ValidationError

from app.config import Settings


def test_non_local_environment_rejects_development_credentials():
    with pytest.raises(ValidationError, match="development credentials are forbidden"):
        Settings(environment="production")


def test_non_local_environment_accepts_replaced_credentials():
    configured = Settings(
        environment="production",
        database_url="postgresql+psycopg://cad:strong-secret@db/cad",
        worker_enrollment_token="worker-enrollment-secret-replaced",
        manual_api_token="manual-api-secret-replaced",
    )
    assert configured.environment == "production"
