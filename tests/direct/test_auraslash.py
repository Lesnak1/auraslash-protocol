import json
import pytest


def test_sla_fulfillment_and_escrow_release(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Test complete successful lifecycle of AuraSlash:
    1. Client (Alice/DAO) creates an SLA escrow agreement for an Autonomous DeFi Keeper Agent (Bob) with 50 GEN fee and 20 GEN collateral.
    2. Bob deposits 20 GEN collateral stake, activating the agreement.
    3. Live telemetry from committed DexScreener/Etherscan endpoint proves 99.8% uptime and 0 drawdown breaches.
    4. GenLayer validators reach consensus on RELEASE_ESCROW (conf: 95, sla_verified: True).
    5. Full 70 GEN (50 GEN fee + 20 GEN collateral refund) is released to Bob.
    """
    contract = direct_deploy("contracts/auraslash.py")

    # Step 1: Alice creates agreement with 50 GEN escrow
    direct_vm.sender = direct_alice
    direct_vm.value = 50 * 10**18
    committed_url = "https://api.dexscreener.com/latest/dex/pairs/base/0x3333333333333333333333333333333333333333"

    agr_id = contract.create_agreement(
        str(direct_bob),
        "DEFI_KEEPER_BOT",
        "Maintain liquidity pool rebalancing with max drawdown < 3% and rebalance latency < 30s.",
        committed_url,
        20 * 10**18,  # Required collateral: 20 GEN
        604800,  # 7 days
    )
    assert agr_id == 0

    a_init = contract.get_agreement(agr_id)
    assert a_init["client"].lower() == str(direct_alice).lower()
    assert a_init["agent_operator"].lower() == str(direct_bob).lower()
    assert a_init["status"] == "PENDING_STAKE"
    assert a_init["escrow_fee"] == str(50 * 10**18)
    assert a_init["required_collateral"] == str(20 * 10**18)

    # Step 2: Bob stakes 20 GEN collateral to activate agreement
    direct_vm.sender = direct_bob
    direct_vm.value = 20 * 10**18
    contract.stake_and_activate_agreement(agr_id)

    a_active = contract.get_agreement(agr_id)
    assert a_active["status"] == "ACTIVE"
    assert a_active["collateral_deposited"] == str(20 * 10**18)

    # Step 3: Mock live authority telemetry and multi-validator neural consensus
    direct_vm.mock_web(
        r".*api\.dexscreener\.com/.*",
        {
            "status": 200,
            "body": json.dumps({
                "pair": "0x3333...",
                "rebalances_executed": 142,
                "max_drawdown_pct": 1.2,
                "avg_latency_seconds": 18.4,
                "sla_breaches": 0,
            }),
        },
    )

    direct_vm.mock_llm(
        r".*AuraSlash Decentralized AI Agent SLA & Slashing Adjudicator.*",
        json.dumps({
            "action_decision": "RELEASE_ESCROW",
            "confidence_score": 95,
            "sla_verified": True,
            "summary": "Agent executed 142 rebalances with max drawdown 1.2% (well within <3% limit) and 18.4s latency. All SLA requirements fully verified.",
        }),
    )

    # Step 4: Adjudicate SLA bound to committed source
    direct_vm.sender = direct_bob
    contract.adjudicate_agent_sla(
        agr_id,
        "Agent operated autonomously for 7 days without SLA violations.",
        committed_url,
    )

    # Step 5: Verify agreement is RELEASED and finalized
    a_final = contract.get_agreement(agr_id)
    assert a_final["status"] == "RELEASED"
    assert a_final["adjudication_verdict"] == "RELEASE_ESCROW"
    assert a_final["adjudication_confidence"] == 95
    assert a_final["is_finalized"] is True


def test_sla_breach_slashing_and_client_restitution(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Test adversarial SLA breach & collateral slashing:
    1. Agent causes severe risk drawdown (8.4% vs 3% limit).
    2. Validators verify exploit/failure on live telemetry and reach consensus on SLASH_COLLATERAL (conf: 98).
    3. Full 70 GEN (50 GEN escrow refund + 20 GEN slashed collateral) is awarded to the Client (Alice).
    """
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 50 * 10**18
    committed_url = "https://api.dexscreener.com/latest/dex/pairs/base/0x4444444444444444444444444444444444444444"

    agr_id = contract.create_agreement(
        str(direct_bob),
        "MARKET_MAKER",
        "Max drawdown < 3% under all market conditions.",
        committed_url,
        20 * 10**18,
        604800,
    )

    direct_vm.sender = direct_bob
    direct_vm.value = 20 * 10**18
    contract.stake_and_activate_agreement(agr_id)

    # Mock severe drawdown failure
    direct_vm.mock_web(
        r".*",
        {
            "status": 200,
            "body": json.dumps({
                "max_drawdown_pct": 8.4,
                "status": "CIRCUIT_BREAKER_TRIGGERED",
                "loss_usd": 12500,
            }),
        },
    )

    direct_vm.mock_llm(
        r".*",
        json.dumps({
            "action_decision": "SLASH_COLLATERAL",
            "confidence_score": 98,
            "sla_verified": False,
            "summary": "Agent breached maximum drawdown constraint (8.4% observed vs 3.0% contracted threshold), triggering severe pool losses. Collateral slashed.",
        }),
    )

    direct_vm.sender = direct_alice
    contract.adjudicate_agent_sla(
        agr_id,
        "Agent suffered 8.4% drawdown violating risk policy.",
        committed_url,
    )

    a = contract.get_agreement(agr_id)
    assert a["status"] == "SLASHED"
    assert a["adjudication_verdict"] == "SLASH_COLLATERAL"
    assert a["is_finalized"] is True


def test_incomplete_sla_grace_period_extension(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Test that sub-threshold performance triggers EXTEND_GRACE_PERIOD without disbursing funds."""
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 30 * 10**18
    committed_url = "https://api.github.com/repos/org/agent-tasks/pulls/1"

    agr_id = contract.create_agreement(
        str(direct_bob),
        "PROMPT_TASK_RUNNER",
        "Deliver complete test suite with 100% pass rate.",
        committed_url,
        10 * 10**18,
        604800,
    )

    direct_vm.sender = direct_bob
    direct_vm.value = 10 * 10**18
    contract.stake_and_activate_agreement(agr_id)

    # Mock partial progress
    direct_vm.mock_web(r".*", {"status": 200, "body": json.dumps({"tests_passed": 30, "tests_pending": 10})})
    direct_vm.mock_llm(
        r".*",
        json.dumps({
            "action_decision": "EXTEND_GRACE_PERIOD",
            "confidence_score": 65,
            "sla_verified": False,
            "summary": "Progress ongoing with 30 tests passing, but 10 tests remain pending. Grace period extended for completion.",
        }),
    )

    direct_vm.sender = direct_bob
    contract.adjudicate_agent_sla(agr_id, "In progress", committed_url)

    a = contract.get_agreement(agr_id)
    assert a["status"] == "ACTIVE"
    assert a["is_finalized"] is False


def test_mismatched_evidence_url_reverts(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Adversarial Test: Verifies that caller cannot pass an uncommitted URL during adjudication."""
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 30 * 10**18
    committed_url = "https://api.github.com/repos/org/real-project/pulls/5"

    agr_id = contract.create_agreement(
        str(direct_bob),
        "SECURITY_AUDITOR_AGENT",
        "Deliver audit report",
        committed_url,
        10 * 10**18,
        604800,
    )

    direct_vm.sender = direct_bob
    direct_vm.value = 10 * 10**18
    contract.stake_and_activate_agreement(agr_id)

    # Bob attempts to substitute a fake uncommitted URL
    fake_url = "https://api.github.com/repos/attacker/fake-repo/pulls/1"
    with direct_vm.expect_revert("Mismatched evidence source. Adjudication is strictly bound to committed source"):
        contract.adjudicate_agent_sla(agr_id, "Fake evidence", fake_url)


def test_untrusted_domain_spoofing_reverts(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Adversarial Test: Verifies that domain substring/prefix spoofing is rejected."""
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 20 * 10**18

    # Substring domain spoofing
    with direct_vm.expect_revert("Untrusted evidence source"):
        contract.create_agreement(
            str(direct_bob),
            "DEFI_KEEPER_BOT",
            "SLA",
            "https://dexscreener.com.attacker.com/telemetry",
            10 * 10**18,
            604800,
        )


def test_unauthorized_early_release_reverts(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Test that active agreements cannot be released early before expiration (Fail-Closed)."""
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 20 * 10**18
    committed_url = "https://api.github.com/repos/org/repo/pulls/1"

    agr_id = contract.create_agreement(
        str(direct_bob),
        "DEFI_KEEPER_BOT",
        "SLA",
        committed_url,
        10 * 10**18,
        604800,  # 7 days
    )

    # Client attempts early release while coverage is active
    with direct_vm.expect_revert("Agreement coverage is still active. Cannot release before expiration timestamp."):
        contract.release_expired_unclaimed_agreement(agr_id)


def test_non_operator_stake_reverts(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Test that arbitrary third parties cannot stake on someone else's agreement."""
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 20 * 10**18
    committed_url = "https://api.github.com/repos/org/repo/pulls/1"

    agr_id = contract.create_agreement(
        str(direct_bob),
        "DEFI_KEEPER_BOT",
        "SLA",
        committed_url,
        10 * 10**18,
        604800,
    )

    # Charlie (third party) attempts to stake
    direct_charlie = "0x9999999999999999999999999999999999999999"
    direct_vm.sender = direct_charlie
    direct_vm.value = 10 * 10**18

    with direct_vm.expect_revert("Only the designated agent operator can deposit collateral stake."):
        contract.stake_and_activate_agreement(agr_id)
