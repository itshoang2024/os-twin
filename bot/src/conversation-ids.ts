export function connectorConversationId(platform: string, userId: string): string {
  return `connector:${platform}:${userId}`;
}

export function draftConversationId(platform: string, userId: string): string {
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  return `${connectorConversationId(platform, userId)}:draft:${suffix}`;
}
