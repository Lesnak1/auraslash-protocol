import { createClient, createAccount, generatePrivateKey, type Address } from 'genlayer-js';
import { testnetBradbury, studionet, localnet } from 'genlayer-js/chains';

/**
 * AuraSlash GenLayer Client Integration SDK
 * Complete TypeScript bindings for all intelligent contract methods on GenLayer:
 * - create_agreement (Client deposits service escrow fee and defines SLA constraints)
 * - stake_and_activate_agreement (Agent deposits collateral bond to activate agreement)
 * - adjudicate_agent_sla (Triggers multi-validator neural consensus over live authority telemetry)
 * - release_expired_unclaimed_agreement (Unlocks expired agreements fail-closed)
 * - get_agreement (Read-only view of agreement state, SLA bounds, and consensus verdict)
 * - get_protocol_stats (Read-only view of active agreements and locked liabilities)
 */

export const DEFAULT_AURASLASH_ADDRESS: Address = '0xA7f9c2448B66B1b1d7d0823FBEB5A967732d888';

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
  is_finalized: bool;
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
 * Creates an AI Agent Service Agreement and deposits service escrow.
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
    address: contractAddress,
    functionName: 'create_agreement',
    args: [
      agentOperator,
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
 * Agent operator deposits collateral bond to activate agreement.
 */
export async function stakeAndActivateAgreement(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  agreementId: bigint | number,
  collateralGenAmount: string | number
): Promise<`0x${string}`> {
  const stakeWei = BigInt(Math.floor(Number(collateralGenAmount) * 1e18));

  const txHash = await client.writeContract({
    address: contractAddress,
    functionName: 'stake_and_activate_agreement',
    args: [BigInt(agreementId)],
    value: stakeWei,
  });

  return txHash as `0x${string}`;
}

/**
 * Evaluates live telemetry evidence and triggers multi-validator neural consensus adjudication.
 */
export async function adjudicateAgentSla(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  agreementId: bigint | number,
  performanceNotes: string,
  submittedEvidenceUrl: string = ''
): Promise<`0x${string}`> {
  const txHash = await client.writeContract({
    address: contractAddress,
    functionName: 'adjudicate_agent_sla',
    args: [BigInt(agreementId), performanceNotes, submittedEvidenceUrl],
    value: BigInt(0),
  });

  return txHash as `0x${string}`;
}

/**
 * Releases expired agreement fail-closed.
 */
export async function releaseExpiredAgreement(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  agreementId: bigint | number
): Promise<`0x${string}`> {
  const txHash = await client.writeContract({
    address: contractAddress,
    functionName: 'release_expired_unclaimed_agreement',
    args: [BigInt(agreementId)],
    value: BigInt(0),
  });

  return txHash as `0x${string}`;
}

/**
 * Queries agreement details from contract storage.
 */
export async function getAgreement(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  agreementId: bigint | number
): Promise<AgreementState> {
  const data = await client.readContract({
    address: contractAddress,
    functionName: 'get_agreement',
    args: [BigInt(agreementId)],
  });

  return data as unknown as AgreementState;
}

/**
 * Queries protocol-wide statistics.
 */
export async function getProtocolStats(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address
): Promise<ProtocolStats> {
  const data = await client.readContract({
    address: contractAddress,
    functionName: 'get_protocol_stats',
    args: [],
  });

  return data as unknown as ProtocolStats;
}

/**
 * Waits for transaction finality on GenLayer.
 */
export async function waitForTransactionReceipt(
  client: ReturnType<typeof getGenLayerClient>,
  hash: `0x${string}`
) {
  return await client.waitForTransactionReceipt({ hash });
}
