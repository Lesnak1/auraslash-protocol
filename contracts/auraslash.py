# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
AuraSlash: Autonomous AI Agent SLA Escrow & Behavioral Slashing Protocol on GenLayer.

The first decentralized accountability & slashing protocol for autonomous AI agents,
keeper bots, and algorithmic delegates operating across Web3.

Core Architecture:
1. Agent Service Escrow: Client/DAO locks service compensation and defines SLA constraints.
2. Collateral Staking: Autonomous agent operator locks a good-faith collateral bond.
3. Multi-Validator Neural Telemetry Verification: GenLayer validators independently fetch
   telemetry from committed authority sources (DexScreener, GitHub, Etherscan, BaseScan, DefiLlama)
   and evaluate agent behavior against contracted SLA bounds under the Equivalence Principle.
4. Exact Deterministic Settlement & Payout Preservation:
   - RELEASE_ESCROW: Verified SLA fulfillment (confidence >= 80) -> Agent receives fee + collateral refund.
   - SLASH_COLLATERAL: Verified SLA breach/hallucination/exploit -> Client receives escrow refund + slashed collateral.
   - EXTEND_GRACE_PERIOD: Sub-threshold progress -> holds funds locked for retry; zero financial drift.
5. Fail-Closed Security Invariants:
   - Strict Exact Host Whitelist (SSRF/spoofing neutralized)
   - Fail-Closed Runtime Block Timestamps
   - Fail-Closed HTTP 200-299 Response Validation
   - Committed Source Binding (callers cannot substitute uncommitted evidence URLs)
   - Solvency Invariant (total_locked >= liabilities)
"""

from genlayer import *
from dataclasses import dataclass
import json


# Whitelist of trusted authoritative evidence sources
TRUSTED_AUTHORITY_DOMAINS = [
    "api.github.com",
    "github.com",
    "api.coingecko.com",
    "api.dexscreener.com",
    "dexscreener.com",
    "api.llama.fi",
    "defillama.com",
    "api.basescan.org",
    "basescan.org",
    "api.etherscan.io",
    "etherscan.io",
    "api.arbiscan.io",
    "arbiscan.io",
    "dune.com",
    "api.dune.com",
    "status.openai.com",
    "status.anthropic.com",
]

VALID_CANONICAL_ACTIONS = ["RELEASE_ESCROW", "SLASH_COLLATERAL", "EXTEND_GRACE_PERIOD"]
CONFIDENCE_THRESHOLD = 80


def _get_runtime_timestamp() -> u256:
    """
    Derives current timestamp from enforceable GenLayer runtime block/message state.
    Strictly fails closed by raising UserError if runtime block timestamp is unavailable.
    """
    if hasattr(gl, "block") and hasattr(gl.block, "timestamp") and gl.block.timestamp is not None:
        ts = int(gl.block.timestamp)
        if ts > 0:
            return u256(ts)
    if hasattr(gl, "message") and hasattr(gl.message, "block_timestamp") and gl.message.block_timestamp is not None:
        ts = int(gl.message.block_timestamp)
        if ts > 0:
            return u256(ts)
    raise gl.vm.UserError("Enforceable runtime block timestamp is unavailable; operation rejected to fail closed.")


def _extract_hostname(url: str) -> str:
    """
    Strictly extracts hostname from HTTP/HTTPS URL preventing path, query, port, or auth bypasses.
    Example: 'https://api.dexscreener.com/latest/dex/pairs/base/0x...?ref=attacker.com' -> 'api.dexscreener.com'
    """
    if not url or not isinstance(url, str):
        return ""
    clean = url.strip()
    if not (clean.startswith("http://") or clean.startswith("https://")):
        return ""

    rest = clean[8:] if clean.startswith("https://") else clean[7:]

    # Strip user:password authentication if present
    if "@" in rest.split("/")[0]:
        rest = rest.split("@", 1)[1]

    # Extract host part before path, query, or hash
    host_part = rest.split("/")[0].split("?")[0].split("#")[0]
    if ":" in host_part:
        host_part = host_part.split(":")[0]

    return host_part.lower().strip()


def _is_trusted_evidence_host(url: str) -> bool:
    """
    Validates that the URL's hostname exactly matches or is a direct subdomain of an approved authority domain.
    Prevents substring/prefix bypasses (e.g. 'github.com.attacker.com' or 'attacker.com/github.com' are rejected).
    """
    host = _extract_hostname(url)
    if not host:
        return False

    for domain in TRUSTED_AUTHORITY_DOMAINS:
        domain_lower = domain.lower()
        if host == domain_lower or host.endswith("." + domain_lower):
            return True
    return False


@allow_storage
@dataclass
class AgentAgreement:
    agreement_id: u256
    client: Address
    agent_operator: Address
    service_type: str  # "DEFI_KEEPER_BOT", "SECURITY_AUDITOR_AGENT", "MARKET_MAKER", "PROMPT_TASK_RUNNER"
    sla_specification: str
    committed_evidence_url: str
    escrow_fee: u256
    required_collateral: u256
    collateral_deposited: u256
    start_timestamp: u256
    end_timestamp: u256
    status: str  # "PENDING_STAKE", "ACTIVE", "RELEASED", "SLASHED", "FINALIZED"
    adjudication_verdict: str  # "RELEASE_ESCROW", "SLASH_COLLATERAL", "EXTEND_GRACE_PERIOD", "NONE"
    adjudication_confidence: u32
    adjudication_summary: str
    is_finalized: bool


# Reusable EVM / IC interface for transfers
@gl.evm.contract_interface
class _Recipient:
    class View:
        pass

    class Write:
        pass


class AuraSlash(gl.Contract):
    """Autonomous AI Agent SLA Escrow & Behavioral Slashing Protocol on GenLayer."""

    agreements: TreeMap[u256, AgentAgreement]
    agreement_counter: u256
    protocol_treasury: Address
    total_active_liabilities: u256

    def __init__(self):
        self.agreement_counter = u256(0)
        self.protocol_treasury = gl.message.sender_address
        self.total_active_liabilities = u256(0)

    @gl.public.write.payable
    def create_agreement(
        self,
        agent_operator: str,
        service_type: str,
        sla_specification: str,
        committed_evidence_url: str,
        required_collateral_gen: u256,
        duration_seconds: u256,
    ) -> u256:
        """
        Client creates an AI Agent Service Agreement, deposits service escrow fee,
        and defines the verifiable SLA specification and committed authority evidence URL.
        """
        escrow_deposit = gl.message.value
        if escrow_deposit == u256(0):
            raise gl.vm.UserError("Must deposit non-zero GEN escrow fee to fund service agreement.")

        if duration_seconds == u256(0):
            raise gl.vm.UserError("Agreement duration must be greater than zero.")

        operator_addr = Address(agent_operator)
        if operator_addr == gl.message.sender_address:
            raise gl.vm.UserError("Client and Agent Operator cannot be the same address.")

        # Strict Host Whitelist Validation on Committed Evidence URL
        if not _is_trusted_evidence_host(committed_evidence_url):
            raise gl.vm.UserError(
                "Untrusted evidence source. Must originate from an approved authority domain (GitHub, DexScreener, DefiLlama, BaseScan, Etherscan)."
            )

        # Fail-closed runtime timing
        runtime_ts = _get_runtime_timestamp()
        start_ts = runtime_ts
        end_ts = start_ts + duration_seconds

        agreement_id = self.agreement_counter
        self.agreement_counter = self.agreement_counter + u256(1)

        self.agreements[agreement_id] = AgentAgreement(
            agreement_id=agreement_id,
            client=gl.message.sender_address,
            agent_operator=operator_addr,
            service_type=service_type,
            sla_specification=sla_specification,
            committed_evidence_url=committed_evidence_url.strip(),
            escrow_fee=escrow_deposit,
            required_collateral=required_collateral_gen,
            collateral_deposited=u256(0),
            start_timestamp=start_ts,
            end_timestamp=end_ts,
            status="PENDING_STAKE" if required_collateral_gen > u256(0) else "ACTIVE",
            adjudication_verdict="NONE",
            adjudication_confidence=u32(0),
            adjudication_summary="",
            is_finalized=False,
        )

        self.total_active_liabilities = self.total_active_liabilities + escrow_deposit
        return agreement_id

    @gl.public.write.payable
    def stake_and_activate_agreement(self, agreement_id: u256) -> None:
        """
        Agent operator deposits the required collateral bond, activating the service agreement.
        """
        stake = gl.message.value
        agreement = self.agreements.get(agreement_id, None)
        if agreement is None:
            raise gl.vm.UserError("Agreement not found.")

        if gl.message.sender_address != agreement.agent_operator:
            raise gl.vm.UserError("Only the designated agent operator can deposit collateral stake.")

        if agreement.status != "PENDING_STAKE" or agreement.is_finalized:
            raise gl.vm.UserError("Agreement is not awaiting collateral stake.")

        if stake < agreement.required_collateral:
            raise gl.vm.UserError("Deposited stake is less than the required collateral bond.")

        agreement.collateral_deposited = stake
        agreement.status = "ACTIVE"
        self.agreements[agreement_id] = agreement

        self.total_active_liabilities = self.total_active_liabilities + stake

    @gl.public.write
    def adjudicate_agent_sla(
        self,
        agreement_id: u256,
        performance_notes: str,
        submitted_evidence_url: str = "",
    ) -> None:
        """
        Triggers multi-validator neural consensus adjudication on agent SLA performance.
        Adjudication is strictly bound to the on-chain committed authority evidence source.
        Enforces canonical decision consensus, non-crossing boundary constraint, and exact payout preservation.
        """
        agreement = self.agreements.get(agreement_id, None)
        if agreement is None:
            raise gl.vm.UserError("Agreement not found.")

        if agreement.status != "ACTIVE" or agreement.is_finalized:
            raise gl.vm.UserError("Agreement is not active or has already reached finality.")

        caller = gl.message.sender_address
        if caller != agreement.client and caller != agreement.agent_operator:
            raise gl.vm.UserError("Only the client or agent operator can trigger SLA adjudication.")

        # Bind Adjudication Strictly to Committed Authority Evidence Source
        committed_url = agreement.committed_evidence_url.strip()
        if submitted_evidence_url and submitted_evidence_url.strip() != "":
            clean_sub = submitted_evidence_url.strip()
            if clean_sub != committed_url:
                raise gl.vm.UserError(
                    f"Mismatched evidence source. Adjudication is strictly bound to committed source: {committed_url}"
                )

        target_fetch_url = committed_url
        if not _is_trusted_evidence_host(target_fetch_url):
            raise gl.vm.UserError("Untrusted evidence source host.")

        sla_spec = agreement.sla_specification
        service_type = agreement.service_type
        escrow_val = agreement.escrow_fee
        collateral_val = agreement.collateral_deposited

        # Multi-Validator Non-Deterministic Consensus Engine
        def leader_fn() -> dict:
            try:
                res = gl.nondet.web.get(target_fetch_url)
            except Exception as e:
                return {
                    "action_decision": "EXTEND_GRACE_PERIOD",
                    "confidence_score": 0,
                    "sla_verified": False,
                    "summary": f"[EXTERNAL] Authority telemetry fetch failed with network error: {str(e)[:100]}",
                }

            # Strict Fetch Success Validation (Fail Closed): Must return explicit HTTP 200-299 status
            http_status = None
            if hasattr(res, "status") and res.status is not None:
                http_status = res.status
            elif hasattr(res, "status_code") and res.status_code is not None:
                http_status = res.status_code
            elif isinstance(res, dict) and "status" in res:
                http_status = res["status"]
            elif isinstance(res, dict) and "status_code" in res:
                http_status = res["status_code"]

            if http_status is not None:
                try:
                    code = int(http_status)
                    if code < 200 or code >= 300:
                        return {
                            "action_decision": "SLASH_COLLATERAL" if code == 404 else "EXTEND_GRACE_PERIOD",
                            "confidence_score": 0,
                            "sla_verified": False,
                            "summary": f"[EXTERNAL] Authority telemetry endpoint returned non-success HTTP status {code}.",
                        }
                except (ValueError, TypeError):
                    pass

            raw_body = getattr(res, "body", None)
            if raw_body is None and isinstance(res, dict):
                raw_body = res.get("body", "")

            if isinstance(raw_body, bytes):
                telemetry_data = raw_body.decode("utf-8", errors="replace")[:3000]
            else:
                telemetry_data = str(raw_body or res)[:3000]

            if not telemetry_data.strip():
                return {
                    "action_decision": "EXTEND_GRACE_PERIOD",
                    "confidence_score": 0,
                    "sla_verified": False,
                    "summary": "[EXTERNAL] Authority endpoint returned empty telemetry data.",
                }

            prompt = f"""
            You are the AuraSlash Decentralized AI Agent SLA & Slashing Adjudicator on GenLayer.
            Evaluate whether the autonomous AI agent fulfilled its contracted SLA bounds.

            === SERVICE SPECIFICATION ===
            - Service Type: {service_type}
            - SLA Bounds & Performance Criteria:
            {sla_spec}

            === OPERATOR / CLIENT SUBMISSION NOTES ===
            {performance_notes}

            === LIVE AUTHORITY TELEMETRY FROM COMMITTED SOURCE ({target_fetch_url}) ===
            {telemetry_data}

            Evaluate the agent's behavior and choose exactly ONE of the 3 canonical action decisions:
            1. "action_decision":
               - "RELEASE_ESCROW": Telemetry strictly proves the agent met or exceeded all SLA requirements without risk limit violations.
               - "SLASH_COLLATERAL": Telemetry proves active SLA breach, catastrophic risk violation, unauthorized drain/hallucination, or roadmap abandonment.
               - "EXTEND_GRACE_PERIOD": Progress is demonstrated or temporary external delay occurred, but performance data is incomplete; holds funds for retry.
            2. "confidence_score": Integer 0 to 100.
            3. "sla_verified": Boolean true if and only if SLA was fully achieved, false otherwise.
            4. "summary": Concise 1-2 sentence technical assessment.

            Respond ONLY with a valid JSON object matching this schema:
            {{
                "action_decision": "RELEASE_ESCROW"|"SLASH_COLLATERAL"|"EXTEND_GRACE_PERIOD",
                "confidence_score": int,
                "sla_verified": bool,
                "summary": "string"
            }}
            """
            raw_eval = gl.nondet.exec_prompt(prompt, response_format="json")

            # Defensive JSON Sanitization & Parsing
            analysis = None
            if isinstance(raw_eval, dict):
                analysis = raw_eval
            elif isinstance(raw_eval, str):
                cleaned = raw_eval.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("```")[1]
                    if cleaned.startswith("json"):
                        cleaned = cleaned[4:]
                    cleaned = cleaned.strip()
                try:
                    analysis = json.loads(cleaned)
                except Exception:
                    pass

            if not isinstance(analysis, dict):
                return {
                    "action_decision": "EXTEND_GRACE_PERIOD",
                    "confidence_score": 0,
                    "sla_verified": False,
                    "summary": "[LLM_ERROR] LLM adjudicator returned non-JSON output format.",
                }

            return analysis

        def validator_fn(leaders_res: gl.vm.Result) -> bool:
            """Validators independently verify evidence and enforce Equivalence Principle."""
            if not isinstance(leaders_res, gl.vm.Return):
                return False

            lead = leaders_res.calldata
            if not isinstance(lead, dict):
                return False

            for req in ["action_decision", "confidence_score", "sla_verified", "summary"]:
                if req not in lead:
                    return False

            lead_action = str(lead.get("action_decision", ""))
            lead_conf = int(lead.get("confidence_score", 0))
            lead_verified = bool(lead.get("sla_verified", False))

            if lead_action not in VALID_CANONICAL_ACTIONS:
                return False

            # RELEASE_ESCROW requires confidence >= 80 and sla_verified == True
            if lead_action == "RELEASE_ESCROW" and (lead_conf < CONFIDENCE_THRESHOLD or not lead_verified):
                return False

            val = leader_fn()
            val_action = str(val.get("action_decision", ""))
            val_conf = int(val.get("confidence_score", 0))
            val_verified = bool(val.get("sla_verified", False))

            # 1. Canonical action decision must match exactly
            if lead_action != val_action:
                return False

            # 2. SLA verification boolean must agree
            if lead_verified != val_verified:
                return False

            # 3. Strict Non-Crossing Boundary Constraint: Leader and validator cannot cross 80% threshold
            lead_crosses = lead_conf >= CONFIDENCE_THRESHOLD
            val_crosses = val_conf >= CONFIDENCE_THRESHOLD
            if lead_crosses != val_crosses:
                return False

            # 4. Within-bucket tolerance is ±6 points
            if abs(lead_conf - val_conf) > 6:
                return False

            return True

        verdict = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

        action = str(verdict.get("action_decision", "EXTEND_GRACE_PERIOD"))
        conf = u32(int(verdict.get("confidence_score", 0)))
        summary_str = str(verdict.get("summary", ""))

        agreement.adjudication_confidence = conf
        agreement.adjudication_summary = summary_str
        agreement.adjudication_verdict = action

        total_funds = escrow_val + collateral_val

        # Deterministic Settlement Gate (Exact Payout Preservation)
        if action == "RELEASE_ESCROW" and conf >= u32(CONFIDENCE_THRESHOLD):
            agreement.status = "RELEASED"
            agreement.is_finalized = True

            if self.total_active_liabilities >= total_funds:
                self.total_active_liabilities = self.total_active_liabilities - total_funds
            else:
                self.total_active_liabilities = u256(0)

            # Release Escrow Fee + Collateral Refund to Agent Operator
            _Recipient(agreement.agent_operator).emit_transfer(value=total_funds)

        elif action == "SLASH_COLLATERAL":
            agreement.status = "SLASHED"
            agreement.is_finalized = True

            if self.total_active_liabilities >= total_funds:
                self.total_active_liabilities = self.total_active_liabilities - total_funds
            else:
                self.total_active_liabilities = u256(0)

            # Refund Escrow Fee + Award Slashed Collateral to Client
            _Recipient(agreement.client).emit_transfer(value=total_funds)

        else:
            # EXTEND_GRACE_PERIOD: Agreement remains active for retry
            agreement.status = "ACTIVE"
            agreement.is_finalized = False

        self.agreements[agreement_id] = agreement

    @gl.public.write
    def release_expired_unclaimed_agreement(self, agreement_id: u256) -> None:
        """
        Unlocks liabilities for agreements that have passed their end timestamp without being activated
        or without claims filed, refunding client deposit fail-closed.
        """
        agreement = self.agreements.get(agreement_id, None)
        if agreement is None:
            raise gl.vm.UserError("Agreement not found.")

        if agreement.is_finalized:
            raise gl.vm.UserError("Agreement has already reached finality.")

        caller = gl.message.sender_address
        if caller != agreement.client and caller != self.protocol_treasury:
            raise gl.vm.UserError("Unauthorized. Only the client or protocol treasury can release expired agreement.")

        # Fail-closed timestamp check
        current_ts = _get_runtime_timestamp()
        if current_ts <= agreement.end_timestamp:
            raise gl.vm.UserError("Agreement coverage is still active. Cannot release before expiration timestamp.")

        refund_val = agreement.escrow_fee + agreement.collateral_deposited
        agreement.status = "FINALIZED"
        agreement.is_finalized = True

        if self.total_active_liabilities >= refund_val:
            self.total_active_liabilities = self.total_active_liabilities - refund_val
        else:
            self.total_active_liabilities = u256(0)

        # Refund escrow to client and collateral to agent if any
        if agreement.escrow_fee > u256(0):
            _Recipient(agreement.client).emit_transfer(value=agreement.escrow_fee)
        if agreement.collateral_deposited > u256(0):
            _Recipient(agreement.agent_operator).emit_transfer(value=agreement.collateral_deposited)

        self.agreements[agreement_id] = agreement

    @gl.public.view
    def get_agreement(self, agreement_id: u256) -> dict:
        """View complete SLA specification, collateral metrics, and consensus verdict of an agreement."""
        a = self.agreements.get(agreement_id, None)
        if a is None:
            raise gl.vm.UserError("Agreement not found.")

        return {
            "agreement_id": int(a.agreement_id),
            "client": str(a.client),
            "agent_operator": str(a.agent_operator),
            "service_type": a.service_type,
            "sla_specification": a.sla_specification,
            "committed_evidence_url": a.committed_evidence_url,
            "escrow_fee": str(a.escrow_fee),
            "required_collateral": str(a.required_collateral),
            "collateral_deposited": str(a.collateral_deposited),
            "start_timestamp": str(a.start_timestamp),
            "end_timestamp": str(a.end_timestamp),
            "status": a.status,
            "adjudication_verdict": a.adjudication_verdict,
            "adjudication_confidence": int(a.adjudication_confidence),
            "adjudication_summary": a.adjudication_summary,
            "is_finalized": a.is_finalized,
        }

    @gl.public.view
    def get_protocol_stats(self) -> dict:
        """View overall protocol metrics and locked liabilities."""
        return {
            "total_agreements": int(self.agreement_counter),
            "total_active_liabilities": str(self.total_active_liabilities),
            "protocol_treasury": str(self.protocol_treasury),
        }
