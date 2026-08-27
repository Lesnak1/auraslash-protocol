import { createClient, createAccount, generatePrivateKey, type Address } from 'genlayer-js';
import { testnetBradbury, studionet, localnet } from 'genlayer-js/chains';

/**
 * AuraSlash GenLayer Client Integration SDK
 */

export const DEFAULT_AURASLASH_ADDRESS: Address = '0x71c563d420188047915512702759902641203001';

// Pre-configured Verified Two-Account Testing Personas
export const DEMO_CLIENT_CONFIG = {
  name: 'Client (Sponsor / DAO)',
  address: '0x70997970C51812dc3A010C7d01b50e0d17dc79C8' as Address,
  privateKey: '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80' as `0x${string}`,
};

export const DEMO_OPERATOR_CONFIG = {
  name: 'Agent Operator (Keeper / Bot)',
  address: '0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC' as Address,
  privateKey: '0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d' as `0x${string}`,
};

export interface AgreementState {
  agreement_id: number;
  client: string;
  agent_operator: string;
  service_type: string;
  sla_specification: string;
  committed_evidence_url: string;
  escrow_fee: string;
  required_collateral: string;
  collateral_deposited: string;
  start_timestamp: string;
  end_timestamp: string;
  status: 'PENDING_STAKE' | 'ACTIVE' | 'RELEASED' | 'SLASHED' | 'FINALIZED';
  adjudication_verdict: string;
  adjudication_confidence: number;
  adjudication_summary: string;
  is_finalized: boolean;
}

export interface ProtocolStats {
  total_agreements: number;
  total_active_liabilities: string;
  protocol_treasury: string;
}

export type SupportedChain = 'testnetBradbury' | 'studionet' | 'localnet';

export function getChainConfig(chainType: SupportedChain = 'testnetBradbury') {
  switch (chainType) {
    case 'studionet':
      return studionet;
    case 'localnet':
      return localnet;
    case 'testnetBradbury':
    default:
      return testnetBradbury;
  }
}

export function getGenLayerClient(
  privateKey?: `0x${string}`,
  chainType: SupportedChain = 'testnetBradbury'
) {
  const account = privateKey ? createAccount(privateKey) : createAccount(generatePrivateKey());
  const chain = getChainConfig(chainType);

  return createClient({
    chain,
    account,
  });
}

/**
 * Step 1: Client locks Escrow Fee and creates Agreement bound to committed telemetry.
 */
export async function createAgreement(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  agentOperator: Address,
  serviceType: string,
  slaSpecification: string,
  committedEvidenceUrl: string,
  requiredCollateralGen: string | number,
  durationSeconds: number,
  escrowDepositGen: string | number
): Promise<`0x${string}`> {
  const escrowWei = BigInt(Math.floor(Number(escrowDepositGen) * 1e18));
  const collateralWei = BigInt(Math.floor(Number(requiredCollateralGen) * 1e18));

  const txHash = await client.writeContract({
    address: contractAddress.toLowerCase() as Address,
    functionName: 'create_agreement',
    args: [
      agentOperator.toLowerCase() as Address,
      serviceType,
      slaSpecification,
      committedEvidenceUrl,
      collateralWei,
      BigInt(durationSeconds),
    ],
    value: escrowWei,
  });

  return txHash as `0x${string}`;
}

/**
 * Step 2: Agent Operator signs with Operator key and deposits Collateral Stake.
 */
export async function stakeAndActivateAgreement(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  agreementId: bigint | number,
  collateralGenAmount: string | number
): Promise<`0x${string}`> {
  const stakeWei = BigInt(Math.floor(Number(collateralGenAmount) * 1e18));

  const txHash = await client.writeContract({
    address: contractAddress.toLowerCase() as Address,
    functionName: 'stake_and_activate_agreement',
    args: [BigInt(agreementId)],
    value: stakeWei,
  });

  return txHash as `0x${string}`;
}

/**
 * Step 3: Trigger Multi-Validator Neural Consensus Adjudication.
 */
export async function adjudicateAgentSla(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  agreementId: bigint | number,
  performanceNotes: string,
  submittedEvidenceUrl: string
): Promise<`0x${string}`> {
  const txHash = await client.writeContract({
    address: contractAddress.toLowerCase() as Address,
    functionName: 'adjudicate_agent_sla',
    args: [BigInt(agreementId), performanceNotes, submittedEvidenceUrl],
  });

  return txHash as `0x${string}`;
}

/**
 * View Agreement State.
 */
export async function getAgreement(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  agreementId: bigint | number
): Promise<AgreementState> {
  const data = await client.readContract({
    address: contractAddress.toLowerCase() as Address,
    functionName: 'get_agreement',
    args: [BigInt(agreementId)],
  });

  return data as AgreementState;
}

/**
 * View Protocol Stats.
 */
export async function getProtocolStats(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address
): Promise<ProtocolStats> {
  const data = await client.readContract({
    address: contractAddress.toLowerCase() as Address,
    functionName: 'get_protocol_stats',
  });

  return data as ProtocolStats;
}
