export type EnterpriseMapDensity = 'compact' | 'comfortable' | 'spacious';

export const enterpriseMapDensityScale: Record<EnterpriseMapDensity, number> = {
  compact: 0.78,
  comfortable: 1,
  spacious: 1.22,
};
