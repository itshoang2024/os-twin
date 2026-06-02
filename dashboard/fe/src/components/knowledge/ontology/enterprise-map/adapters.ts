export interface EnterpriseMapAdapterContract {
  source: 'projection' | 'explorer-fallback';
  preservesGraphInstruction: boolean;
}

export const enterpriseMapAdapterContract: EnterpriseMapAdapterContract = {
  source: 'projection',
  preservesGraphInstruction: true,
};
