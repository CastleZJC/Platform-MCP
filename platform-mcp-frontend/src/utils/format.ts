/**
 * 统一 API Key 掩码格式化（对齐 UI 原型 L1094：前 7 + ****** + 后 2）
 *
 * 输入：后端 key_prefix 字段（raw_key[:10]，如 "pmcp_abc"）
 * 输出：如 "pmcp_a******yz"
 *
 * UserPage 和 ProfilePage 共用，避免重复逻辑与运维分歧。
 */
export function maskApiKey(prefix: string | null | undefined): string {
  if (!prefix) return "—"
  return prefix.length >= 8
    ? prefix.slice(0, 7) + "******" + prefix.slice(-2)
    : prefix + "****"
}
