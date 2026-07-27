from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts import OrderStatus, TransitionOrderRequest, WorkerClaimRequest, WorkerClaimResponse


def test_transition_command_forbids_unknown_fields_and_invalid_versions():
    with pytest.raises(ValidationError):
        TransitionOrderRequest(expected_version=-1, target_status=OrderStatus.UPLOADED)
    with pytest.raises(ValidationError):
        TransitionOrderRequest(expected_version=0, target_status=OrderStatus.UPLOADED, status="READY")


def test_worker_claim_rejects_unknown_protocol_major_and_unknown_capability():
    valid = {
        "protocol_version": "1.0",
        "worker_id": uuid4(),
        "capabilities": ["AI_DRAWING"],
        "supported_cad_ir": ["0.1.0"],
        "available_slots": 1,
    }
    assert WorkerClaimRequest(**valid).protocol_version == "1.0"
    with pytest.raises(ValidationError):
        WorkerClaimRequest(**{**valid, "protocol_version": "2.0"})
    with pytest.raises(ValidationError):
        WorkerClaimRequest(**{**valid, "capabilities": ["UNKNOWN"]})


def test_empty_claim_requires_a_retry_instruction():
    assert WorkerClaimResponse(protocol_version="1.0", job=None, retry_after_seconds=5).retry_after_seconds == 5
    with pytest.raises(ValidationError):
        WorkerClaimResponse(protocol_version="1.0", job=None)
