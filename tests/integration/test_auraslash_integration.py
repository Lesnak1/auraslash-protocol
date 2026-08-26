"""
Integration tests for AuraSlash against GenLayer RPC / StudioNet / LocalNet.
"""

import pytest

gltest = pytest.importorskip("gltest", reason="gltest package required for live GenLayer integration tests")
from gltest import get_contract_factory
from gltest.assertions import tx_execution_succeeded


def test_auraslash_deployment_and_schema():
    """Validates contract deployment and schema generation on GenVM."""
    factory = get_contract_factory("contracts/auraslash.py")
    
    contract = factory.deploy(args=[])
    assert contract.address is not None
    assert contract.address.startswith("0x")

    stats = contract.get_protocol_stats().call()
    assert stats is not None
    assert "total_agreements" in stats
