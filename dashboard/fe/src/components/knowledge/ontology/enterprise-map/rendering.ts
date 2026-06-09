export const ENTERPRISE_MAP_RENDERING_SURFACES = ['svg'] as const;

export function isEnterpriseMapActivationKey(key: string) {
  return key === 'Enter' || key === ' ';
}
