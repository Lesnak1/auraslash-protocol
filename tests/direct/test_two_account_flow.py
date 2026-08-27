"""
AuraSlash End-to-End Two-Account Signing & Funding Workflow Verification Script
Demonstrates verifiable interaction between two distinct funded cryptographic accounts:
1. Client (Alice: 0x70997970C51812dc3A010C7d01b50e0d17dc79C8) - Deposits escrow fee, creates SLA contract
2. Agent Operator (Bob: 0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC) - Deposits collateral stake, activates agreement
3. GenLayer Validators - Multi-validator neural consensus adjudication over full observation window
"""

import json
import pytest


def test_e2e_two_account_signing_and_lifecycle_flow(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Two-Account Workflow Verification:
    - Alice signs as Client with Account 1.
    - Bob signs as Operator with Account 2.
    - Verification that non-operator cannot stake and premature release is blocked until observation completes.
    """
    contract = direct_deploy("contracts/auraslash.py")

    # Step 1: Alice (Account 1 - Client) creates service agreement
    direct_vm.sender = direct_alice
    direct_vm.value = 50 * 10**18  # 50 GEN Escrow Deposit
    committed_telemetry_url = "https://api.dexscreener.com/latest/dex/pairs/base/0x8888888888888888888888888888888888888888"

    agreement_id = contract.create_agreement(
        str(direct_bob),  # Designates Bob as the Operator
        "DEFI_KEEPER_BOT",
        "Maintain continuous arbitrage rebalancing with 99.5% uptime and max 0.5% slippage on Base.",
        committed_telemetry_url,
        20 * 10**18,  # Required collateral: 20 GEN
        604800,  # 7-day observation window
    )
    assert agreement_id == 0

    agreement_state = contract.get_agreement(agreement_id)
    assert agreement_state["client"].lower() == str(direct_alice).lower()
    assert agreement_state["agent_operator"].lower() == str(direct_bob).lower()
    assert agreement_state["status"] == "PENDING_STAKE"
    assert agreement_state["escrow_fee"] == str(50 * 10**18)

    # Step 2: Third party (Charlie) attempts to stake -> REVERTS
    charlie_addr = "0x9999999999999999999999999999999999999999"
    direct_vm.sender = charlie_addr
    direct_vm.value = 20 * 10**18
    with direct_vm.expect_revert("Only the designated agent operator can deposit collateral stake."):
        contract.stake_and_activate_agreement(agreement_id)

    # Step 3: Bob (Account 2 - Agent Operator) signs with Operator Key & stakes collateral
    direct_vm.sender = direct_bob
    direct_vm.value = 20 * 10**18
    contract.stake_and_activate_agreement(agreement_id)

    active_state = contract.get_agreement(agreement_id)
    assert active_state["status"] == "ACTIVE"
    assert active_state["collateral_deposited"] == str(20 * 10**18)

    # Step 4: Mid-term evaluation before observation window concludes -> held as ACTIVE
    direct_vm.mock_web(
        r".*",
        {
            "status": 200,
            "body": json.dumps({"uptime_percentage": 99.9, "max_observed_slippage": 0.15, "status": "HEALTHY"}),
        },
    )
    direct_vm.mock_llm(
        r".*",
        json.dumps({
            "action_decision": "RELEASE_ESCROW",
            "confidence_score": 96,
            "sla_verified": True,
            "summary": "Agent is performing flawlessly at 99.9% uptime.",
        }),
    )

    # Mid-term check triggered by Alice
    direct_vm.sender = direct_alice
    contract.adjudicate_agent_sla(agreement_id, "Mid-term check", committed_telemetry_url)

    mid_state = contract.get_agreement(agreement_id)
    assert mid_state["status"] == "ACTIVE", "Escrow cannot be released prematurely before observation window ends"
    assert mid_state["adjudication_verdict"] == "EXTEND_GRACE_PERIOD"

    # Step 5: Advance block timestamp past 7-day observation window
    direct_vm.block_timestamp = direct_vm.block_timestamp + 604801

    # Step 6: Post-observation window adjudication -> RELEASE_ESCROW finalizes
    direct_vm.sender = direct_bob
    contract.adjudicate_agent_sla(agreement_id, "Full observation window completed", committed_telemetry_url)

    final_state = contract.get_agreement(agreement_id)
    assert final_state["status"] == "RELEASED"
    assert final_state["adjudication_verdict"] == "RELEASE_ESCROW"
    assert final_state["adjudication_confidence"] == 96
    assert final_state["is_finalized"] is True

    stats = contract.get_protocol_stats()
    assert stats["total_active_liabilities"] == "0", "Exact payout preservation: 0 liabilities remaining"
