declare module 'genlayer-js' {
  export type Address = `0x${string}`;

  export interface Account {
    address: Address;
    privateKey?: `0x${string}`;
  }

  export interface ClientConfig {
    chain: any;
    account: Account;
  }

  export interface GenLayerClient {
    account: Account;
    chain: any;
    readContract(params: {
      address: Address;
      functionName: string;
      args?: any[];
    }): Promise<any>;
    writeContract(params: {
      address: Address;
      functionName: string;
      args?: any[];
      value?: bigint;
    }): Promise<`0x${string}`>;
    waitForTransactionReceipt(params: { hash: `0x${string}` }): Promise<any>;
  }

  export function createClient(config: ClientConfig): GenLayerClient;
  export function createAccount(privateKey: `0x${string}`): Account;
  export function generatePrivateKey(): `0x${string}`;
}

declare module 'genlayer-js/chains' {
  export const testnetBradbury: any;
  export const studionet: any;
  export const localnet: any;
}
