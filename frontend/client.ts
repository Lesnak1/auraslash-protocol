import { createClient, createAccount, generatePrivateKey, type Address } from 'genlayer-js';
import { testnetBradbury, studionet, localnet } from 'genlayer-js/chains';

/**
 * AuraSlash GenLayer Client Integration SDK
 */

export const DEFAULT_AURASLASH_ADDRESS: Address = '0x71c563d420188047915512702759902641203001';

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

export async function adjudicateAgentSla(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  agreementId: bigint | number,
  performanceNotes: string,
  submittedEvidenceUrl: string = ''
): Promise<`0x${string}`> {
  const txHash = await client.writeContract({
    address: contractAddress.toLowerCase() as Address,
    functionName: 'adjudicate_agent_sla',
    args: [BigInt(agreementId), performanceNotes, submittedEvidenceUrl],
    value: BigInt(0),
  });

  return txHash as `0x${string}`;
}

export async function releaseExpiredAgreement(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address,
  agreementId: bigint | number
): Promise<`0x${string}`> {
  const txHash = await client.writeContract({
    address: contractAddress.toLowerCase() as Address,
    functionName: 'release_expired_unclaimed_agreement',
    args: [BigInt(agreementId)],
    value: BigInt(0),
  });

  return txHash as `0x${string}`;
}

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

  return data as unknown as AgreementState;
}

export async function getProtocolStats(
  client: ReturnType<typeof getGenLayerClient>,
  contractAddress: Address
): Promise<ProtocolStats> {
  const data = await client.readContract({
    address: contractAddress.toLowerCase() as Address,
    functionName: 'get_protocol_stats',
    args: [],
  });

  return data as unknown as ProtocolStats;
}
