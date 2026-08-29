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
    4. Observation window concludes (current_ts >= end_timestamp).
    5. GenLayer validators reach consensus on RELEASE_ESCROW (conf: 95, sla_verified: True).
    6. Full 70 GEN (50 fee + 20 collateral refund) is released to Bob.
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
            "summary": "Agent maintained 99.8% uptime with max slippage 0.21% over 142 rebalances across full observation period.",
        }),
    )

    # Step 4: Advance block timestamp past 7-day observation window
    direct_vm.block_timestamp = direct_vm.block_timestamp + 604801

    # Step 5: Adjudicate SLA bound to committed source
    direct_vm.sender = direct_bob
    contract.adjudicate_agent_sla(
        agr_id,
        "Weekly keeper cycle concluded flawlessly over full observation window.",
        committed_url,
    )

    # Step 6: Verify agreement is RELEASED and finalized
    a_final = contract.get_agreement(agr_id)
    assert a_final["status"] == "RELEASED"
    assert a_final["adjudication_verdict"] == "RELEASE_ESCROW"
    assert a_final["adjudication_confidence"] == 95
    assert a_final["is_finalized"] is True


def test_premature_release_before_observation_window_complete_is_held_as_active(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Steward Verification Test:
    Verifies that irreversible escrow fee release (RELEASE_ESCROW) CANNOT occur
    before the agreed SLA observation window is complete, even if telemetry is healthy.
    The agreement is held as ACTIVE with EXTEND_GRACE_PERIOD and zero funds moved.
    """
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 50 * 10**18
    committed_url = "https://api.dexscreener.com/latest/dex/pairs/base/0x7777777777777777777777777777777777777777"

    agr_id = contract.create_agreement(
        str(direct_bob),
        "DEFI_KEEPER_BOT",
        "Maintain 99.5% uptime for 7 days (604800s)",
        committed_url,
        20 * 10**18,
        604800,
    )

    direct_vm.sender = direct_bob
    direct_vm.value = 20 * 10**18
    contract.stake_and_activate_agreement(agr_id)

    # Mid-term telemetry (e.g. Day 2 of 7)
    direct_vm.mock_web(
        r".*",
        {
            "status": 200,
            "body": json.dumps({"uptime_percentage": 100.0, "status": "HEALTHY"}),
        },
    )

    # LLM proposes RELEASE_ESCROW mid-term
    direct_vm.mock_llm(
        r".*",
        json.dumps({
            "action_decision": "RELEASE_ESCROW",
            "confidence_score": 95,
            "sla_verified": True,
            "summary": "Agent is currently healthy at 100% uptime.",
        }),
    )

    # Trigger adjudication prematurely while observation window is still active
    direct_vm.sender = direct_bob
    contract.adjudicate_agent_sla(agr_id, "Mid-term check on Day 2", committed_url)

    a_mid = contract.get_agreement(agr_id)
    assert a_mid["status"] == "ACTIVE", "Agreement must remain ACTIVE before observation window completes"
    assert a_mid["is_finalized"] is False, "Must NOT reach finality before observation window ends"
    assert a_mid["adjudication_verdict"] == "EXTEND_GRACE_PERIOD"
    assert "[OBSERVATION_ACTIVE]" in a_mid["adjudication_summary"]

    stats_mid = contract.get_protocol_stats()
    assert stats_mid["total_active_liabilities"] == str(70 * 10**18), "Zero funds moved prematurely"

    # Now advance time past the 7-day observation window
    direct_vm.block_timestamp = direct_vm.block_timestamp + 604801

    contract.adjudicate_agent_sla(agr_id, "Final full-term check", committed_url)

    a_end = contract.get_agreement(agr_id)
    assert a_end["status"] == "RELEASED", "Agreement releases escrow after observation window completes"
    assert a_end["is_finalized"] is True


def test_emergency_early_slashing_on_catastrophic_breach(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Steward Verification Test:
    Verifies that legitimate early settlement is explicitly constrained to catastrophic breaches:
    Severe risk violations / circuit breaker triggers allow immediate emergency slashing
    mid-window to protect client funds from further loss.
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

    # Catastrophic breach on Day 1 (drawdown 8.4% vs 3% limit, circuit breaker tripped)
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
            "is_catastrophic_emergency": True,
            "summary": "Agent breached maximum drawdown constraint (8.4% observed vs 3.0% contracted threshold), triggering severe pool losses. Emergency collateral slash approved.",
        }),
    )

    # Client triggers emergency slash mid-window
    direct_vm.sender = direct_alice
    contract.adjudicate_agent_sla(
        agr_id,
        "Agent suffered 8.4% drawdown violating risk policy.",
        committed_url,
    )

    a = contract.get_agreement(agr_id)
    assert a["status"] == "SLASHED", "Catastrophic breach slashes early to protect client capital"
    assert a["adjudication_verdict"] == "SLASH_COLLATERAL"
    assert a["adjudication_confidence"] == 98
    assert a["is_finalized"] is True

    stats = contract.get_protocol_stats()
    assert stats["total_active_liabilities"] == "0"


def test_non_catastrophic_shortfall_mid_window_is_held_in_grace_period_and_never_slashes_early(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Steward Verification Test (Gen. Dave):
    Verifies that a standard, non-catastrophic performance shortfall detected mid-window
    (is_catastrophic_emergency == False) is strictly held in EXTEND_GRACE_PERIOD and NEVER
    slashed early, leaving the agreement active with zero funds moved so the operator
    can recover over the contracted observation window.
    """
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 50 * 10**18
    committed_url = "https://api.dexscreener.com/latest/dex/pairs/base/0x4444444444444444444444444444444444444444"

    agr_id = contract.create_agreement(
        str(direct_bob),
        "DEFI_KEEPER_BOT",
        "Maintain 99.5% uptime and max 0.5% slippage.",
        committed_url,
        20 * 10**18,
        604800,  # 7 days
    )

    direct_vm.sender = direct_bob
    direct_vm.value = 20 * 10**18
    contract.stake_and_activate_agreement(agr_id)

    # Telemetry shows minor sub-par performance (98.2% uptime vs 99.5% target) on Day 2 of 7
    direct_vm.mock_web(
        r".*",
        {
            "status": 200,
            "body": json.dumps({
                "uptime_percentage": 98.2,
                "max_observed_slippage": 0.55,
                "status": "TEMPORARY_LATENCY",
            }),
        },
    )

    # LLM outputs non-catastrophic breach (is_catastrophic_emergency: False)
    direct_vm.mock_llm(
        r".*",
        json.dumps({
            "action_decision": "SLASH_COLLATERAL",
            "confidence_score": 85,
            "sla_verified": False,
            "is_catastrophic_emergency": False,
            "summary": "Agent uptime is slightly under 99.5% target due to temporary network latency.",
        }),
    )

    # Client triggers check mid-window
    direct_vm.sender = direct_alice
    contract.adjudicate_agent_sla(agr_id, "Mid-term check on Day 2", committed_url)

    a = contract.get_agreement(agr_id)
    assert a["status"] == "ACTIVE", "Non-catastrophic shortfall mid-window must NOT slash early"
    assert a["is_finalized"] is False, "Agreement must remain active"
    assert a["adjudication_verdict"] == "EXTEND_GRACE_PERIOD"
    assert "[OBSERVATION_ACTIVE]" in a["adjudication_summary"]

    stats = contract.get_protocol_stats()
    assert stats["total_active_liabilities"] == str(70 * 10**18), "Zero funds moved on mid-window non-catastrophic check"


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


def test_missing_or_malformed_http_status_strictly_forces_retry_and_never_slashes(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Steward Verification Test (Gen. Dave):
    Proves that a missing or malformed HTTP response status (e.g. status: None, status: 'invalid')
    strictly terminates before LLM adjudication and returns EXTEND_GRACE_PERIOD (retry outcome),
    preventing any high-confidence slash or unauthorized escrow transfer.
    """
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 50 * 10**18
    committed_url = "https://api.dexscreener.com/latest/dex/pairs/base/0x8888888888888888888888888888888888888888"

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

    expected_liabilities = str(70 * 10**18)

    # Case A: Missing status (status is None)
    direct_vm.mock_web(
        r".*",
        {"body": "Corrupted response without HTTP status code"},
    )
    direct_vm.sender = direct_alice
    contract.adjudicate_agent_sla(agr_id, "Attempt with missing status", committed_url)

    a_missing = contract.get_agreement(agr_id)
    assert a_missing["status"] == "ACTIVE"
    assert a_missing["is_finalized"] is False
    assert a_missing["adjudication_verdict"] == "EXTEND_GRACE_PERIOD"
    assert a_missing["adjudication_confidence"] == 0
    assert "Missing HTTP response status" in a_missing["adjudication_summary"]
    assert contract.get_protocol_stats()["total_active_liabilities"] == expected_liabilities

    # Case B: Malformed status (status is non-integer string)
    direct_vm.mock_web(
        r".*",
        {"status": "invalid_status", "body": "Non-integer status string"},
    )
    direct_vm.sender = direct_bob
    contract.adjudicate_agent_sla(agr_id, "Attempt with malformed status", committed_url)

    a_malformed = contract.get_agreement(agr_id)
    assert a_malformed["status"] == "ACTIVE"
    assert a_malformed["is_finalized"] is False
    assert a_malformed["adjudication_verdict"] == "EXTEND_GRACE_PERIOD"
    assert a_malformed["adjudication_confidence"] == 0
    assert "Malformed HTTP response status" in a_malformed["adjudication_summary"]
    assert contract.get_protocol_stats()["total_active_liabilities"] == expected_liabilities


def test_null_or_empty_body_strictly_forces_retry_and_never_slashes(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """
    Test that null/missing or whitespace-only response bodies strictly return EXTEND_GRACE_PERIOD
    and never slash.
    """
    contract = direct_deploy("contracts/auraslash.py")

    direct_vm.sender = direct_alice
    direct_vm.value = 50 * 10**18
    committed_url = "https://api.dexscreener.com/latest/dex/pairs/base/0x8888888888888888888888888888888888888888"

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

    # Mock HTTP 200 with null body
    direct_vm.mock_web(
        r".*",
        {"status": 200, "body": None},
    )
    direct_vm.sender = direct_alice
    contract.adjudicate_agent_sla(agr_id, "Attempt with null body", committed_url)

    a_null = contract.get_agreement(agr_id)
    assert a_null["status"] == "ACTIVE"
    assert a_null["is_finalized"] is False
    assert a_null["adjudication_verdict"] == "EXTEND_GRACE_PERIOD"
    assert a_null["adjudication_confidence"] == 0
    assert "null/missing body data" in a_null["adjudication_summary"]

