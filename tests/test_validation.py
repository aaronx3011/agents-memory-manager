import pytest
from pydantic import ValidationError

from agent_memory.models import MemoryInput


def test_verified_memory_requires_timestamp():
    with pytest.raises(ValidationError, match="verified_at"):
        MemoryInput(
            type="semantic", title="Constraint", content="Observed behavior",
            sources=[{"kind": "test", "reference": "test run"}], evidence="verified",
        )


def test_unknown_input_fields_are_rejected():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        MemoryInput(
            type="semantic", title="Constraint", content="Observed behavior",
            sources=[{"kind": "test", "reference": "test run"}], owner_id="untrusted",
        )
