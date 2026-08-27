import json
import pytest


def test_sla_fulfillment_and_escrow_release(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Test complete successful lifecycle of AuraSlash:
    1. Client (Alice) locks 50 GEN escrow fee for autonomous DeFi keeper agent service for 7 days (604800s).
    2. Agent Operator (Bob) deposits 20 GEN collateral stake to activate agreement.
    3. DexScreener live telemetry proves 99.8% uptime and 0 slippage violations.
    4. GenLayer validators reach consensus on RELEASE_ESCROW (conf: 95, sla_verified: True).
    5. Full 70 GEN (50 fee + 20 collateral refund) is released to Bob.
    """
    contract = direct_deploy("contracts/auraslash.py")

    # Step 1: Alice creates agreement with 50 GEN escrow
    direct_vm.sender = direct_alice
    direct_vm.value = 50 * 10**18
    committed_url = "https://api.dexscreener.com/latest/dex/pairs/base/0x3333333333333333333333333333333333333333"

    agr_id = contract.create_agreement(
        str(direct_bob),
        "DEFI_KEEPER_BOT",
        "Maintain continuous arbitrage rebalancing with 99.5% uptime and max 0.5% slippage on Base.",
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
                "pairAddress": "0x3333333333333333333333333333333333333333",
                "uptime_percentage": 99.8,
                "max_observed_slippage": 0.21,
                "rebalance_count_24h": 142,
                "status": "HEALTHY",
            }),
        },
    )

    direct_vm.mock_llm(
        r".*AuraSlash Decentralized AI Agent SLA & Slashing Adjudicator.*",
        json.dumps({
            "action_decision": "RELEASE_ESCROW",
            "confidence_score": 95,
            "sla_verified": True,
            "summary": "Agent maintained 99.8% uptime with max slippage 0.21% over 142 rebalances, meeting all SLA bounds.",
        }),
    )

    # Step 4: Adjudicate SLA bound to committed source
    direct_vm.sender = direct_bob
    contract.adjudicate_agent_sla(
        agr_id,
        "Weekly keeper cycle concluded flawlessly.",
        committed_url,
    )

    # Step 5: Verify agreement is RELEASED and finalized
    a_final = contract.get_agreement(agr_id)
    assert a_final["status"] == "RELEASED"
    assert a_final["adjudication_verdict"] == "RELEASE_ESCROW"
    assert a_final["adjudication_confidence"] == 95
    assert a_final["is_finalized"] is True


def test_repeated_404_responses_leave_agreement_active_and_move_no_funds(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Steward Verification Test:
    Verifies that HTTP 404 responses and repeated fetch/status failures are strictly treated
    as retry outcomes (EXTEND_GRACE_PERIOD), NEVER as evidence for slashing, leaving the agreement
    fully active and moving zero escrow funds.
    """
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 50 * 10**18
    committed_url = "https://api.dexscreener.com/latest/dex/pairs/base/0x5555555555555555555555555555555555555555"

    agr_id = contract.create_agreement(
        str(direct_bob),
        "DEFI_KEEPER_BOT",
        "Maintain uptime > 99%",
        committed_url,
        20 * 10**18,
        604800,
    )

    direct_vm.sender = direct_bob
    direct_vm.value = 20 * 10**18
    contract.stake_and_activate_agreement(agr_id)

    stats_before = contract.get_protocol_stats()
    expected_liabilities = str(70 * 10**18)
    assert stats_before["total_active_liabilities"] == expected_liabilities

    # Step 1: Mock 404 response
    direct_vm.mock_web(r".*", {"status": 404, "body": "Pair not yet indexed on DexScreener"})

    direct_vm.sender = direct_alice
    contract.adjudicate_agent_sla(agr_id, "Checking keeper telemetry", committed_url)

    a1 = contract.get_agreement(agr_id)
    assert a1["status"] == "ACTIVE", "Agreement must remain ACTIVE on 404"
    assert a1["is_finalized"] is False
    assert a1["adjudication_verdict"] == "EXTEND_GRACE_PERIOD"
    assert a1["adjudication_confidence"] == 0

    stats1 = contract.get_protocol_stats()
    assert stats1["total_active_liabilities"] == expected_liabilities

    # Step 2: Repeated 404
    direct_vm.sender = direct_bob
    contract.adjudicate_agent_sla(agr_id, "Second check", committed_url)

    a2 = contract.get_agreement(agr_id)
    assert a2["status"] == "ACTIVE"
    assert a2["is_finalized"] is False
    assert a2["adjudication_verdict"] == "EXTEND_GRACE_PERIOD"

    stats2 = contract.get_protocol_stats()
    assert stats2["total_active_liabilities"] == expected_liabilities, "Liabilities preserved with 0 drift"


def test_sub_threshold_confidence_cannot_slash_and_moves_no_funds(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Test that sub-threshold confidence (conf < 80) strictly prevents collateral slashing."""
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 50 * 10**18
    committed_url = "https://api.dexscreener.com/latest/dex/pairs/base/0x6666666666666666666666666666666666666666"

    agr_id = contract.create_agreement(
        str(direct_bob),
        "DEFI_KEEPER_BOT",
        "Maintain uptime > 99%",
        committed_url,
        20 * 10**18,
        604800,
    )

    direct_vm.sender = direct_bob
    direct_vm.value = 20 * 10**18
    contract.stake_and_activate_agreement(agr_id)

    # Mock ambiguous telemetry with confidence 60 (< 80)
    direct_vm.mock_web(r".*", {"status": 200, "body": json.dumps({"status": "UNCERTAIN_LOGS"})})
    direct_vm.mock_llm(
        r".*",
        json.dumps({
            "action_decision": "SLASH_COLLATERAL",
            "confidence_score": 60,
            "sla_verified": False,
            "summary": "Inconclusive telemetry logs (confidence 60%).",
        }),
    )

    direct_vm.sender = direct_alice
    contract.adjudicate_agent_sla(agr_id, "Attempt slash with weak evidence", committed_url)

    a = contract.get_agreement(agr_id)
    assert a["status"] == "ACTIVE", "Sub-threshold confidence must NOT slash collateral"
    assert a["is_finalized"] is False
    assert a["adjudication_verdict"] == "EXTEND_GRACE_PERIOD"
    assert a["adjudication_confidence"] == 60


def test_sla_breach_slashing_and_client_restitution_with_high_confidence(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Test adversarial SLA breach & collateral slashing with high confidence:
    1. Agent causes severe risk drawdown (8.4% vs 3% limit).
    2. Validators verify exploit/failure on live telemetry and reach consensus on SLASH_COLLATERAL (conf: 98 >= 80).
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
    assert a["adjudication_confidence"] == 98
    assert a["is_finalized"] is True

    stats = contract.get_protocol_stats()
    assert stats["total_active_liabilities"] == "0"


def test_incomplete_sla_grace_period_extension(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Test that sub-threshold performance triggers EXTEND_GRACE_PERIOD without disbursing funds."""
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 50 * 10**18
    committed_url = "https://api.dexscreener.com/latest/dex/pairs/base/0x2222222222222222222222222222222222222222"

    agr_id = contract.create_agreement(
        str(direct_bob),
        "DEFI_KEEPER_BOT",
        "Maintain 99.5% uptime",
        committed_url,
        20 * 10**18,
        604800,
    )

    direct_vm.sender = direct_bob
    direct_vm.value = 20 * 10**18
    contract.stake_and_activate_agreement(agr_id)

    # Mock incomplete run
    direct_vm.mock_web(r".*", {"status": 200, "body": json.dumps({"uptime_percentage": 94.0, "status": "WARMING_UP"})})
    direct_vm.mock_llm(
        r".*",
        json.dumps({
            "action_decision": "EXTEND_GRACE_PERIOD",
            "confidence_score": 70,
            "sla_verified": False,
            "summary": "Agent is currently at 94.0% uptime during warm-up phase. Grace period extended.",
        }),
    )

    direct_vm.sender = direct_bob
    contract.adjudicate_agent_sla(agr_id, "Warmup in progress", committed_url)

    a = contract.get_agreement(agr_id)
    assert a["status"] == "ACTIVE"
    assert a["is_finalized"] is False


def test_mismatched_evidence_url_reverts(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Adversarial Test: Verifies that caller cannot pass an uncommitted evidence URL during adjudication."""
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 50 * 10**18
    committed_url = "https://api.dexscreener.com/latest/dex/pairs/base/0x1111111111111111111111111111111111111111"

    agr_id = contract.create_agreement(
        str(direct_bob),
        "DEFI_KEEPER_BOT",
        "SLA spec",
        committed_url,
        20 * 10**18,
        604800,
    )

    direct_vm.sender = direct_bob
    direct_vm.value = 20 * 10**18
    contract.stake_and_activate_agreement(agr_id)

    # Bob attempts to substitute a fake uncommitted URL
    fake_url = "https://api.dexscreener.com/latest/dex/pairs/base/0x9999999999999999999999999999999999999999"
    with direct_vm.expect_revert("Mismatched evidence source. Adjudication is strictly bound to committed source"):
        contract.adjudicate_agent_sla(agr_id, "Fake cycle", fake_url)


def test_untrusted_domain_spoofing_reverts(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Adversarial Test: Verifies that domain substring/prefix spoofing is rejected."""
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 50 * 10**18

    # Substring domain spoofing
    with direct_vm.expect_revert("Untrusted evidence source"):
        contract.create_agreement(
            str(direct_bob),
            "DEFI_KEEPER_BOT",
            "SLA",
            "https://dexscreener.com.attacker.com/telemetry",
            20 * 10**18,
            604800,
        )


def test_unauthorized_early_release_reverts(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Test that active agreements cannot be released early before expiration (Fail-Closed)."""
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 50 * 10**18
    committed_url = "https://api.dexscreener.com/latest/dex/pairs/base/0x1111111111111111111111111111111111111111"

    agr_id = contract.create_agreement(
        str(direct_bob),
        "DEFI_KEEPER_BOT",
        "Spec",
        committed_url,
        20 * 10**18,
        604800,  # 7 days
    )

    # Client attempts early release while agreement is active
    with direct_vm.expect_revert("Agreement coverage is still active. Cannot release before expiration timestamp."):
        contract.release_expired_unclaimed_agreement(agr_id)


def test_non_operator_stake_reverts(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Test that arbitrary third parties cannot stake on someone else's agreement."""
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 50 * 10**18
    committed_url = "https://api.dexscreener.com/latest/dex/pairs/base/0x1111111111111111111111111111111111111111"

    agr_id = contract.create_agreement(
        str(direct_bob),
        "DEFI_KEEPER_BOT",
        "Spec",
        committed_url,
        20 * 10**18,
        604800,
    )

    # Charlie (third party) attempts to stake
    direct_charlie = "0x9999999999999999999999999999999999999999"
    direct_vm.sender = direct_charlie
    direct_vm.value = 20 * 10**18

    with direct_vm.expect_revert("Only the designated agent operator can deposit collateral stake."):
        contract.stake_and_activate_agreement(agr_id)
