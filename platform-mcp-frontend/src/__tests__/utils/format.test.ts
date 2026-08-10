import { describe, it, expect } from 'vitest'
import { maskApiKey } from '@/utils/format'

describe('maskApiKey', () => {
  it('正常长度前缀 → 前 7 + ****** + 后 2（对齐 UI 原型 L1094）', () => {
    expect(maskApiKey('pmcp_abc')).toBe('pmcp_a******bc')
  })

  it('长前缀 → 截取前 7 + 后 2', () => {
    expect(maskApiKey('pmcp_abcdefghijklmnop')).toBe('pmcp_a******op')
  })

  it('正好 8 字符 → 前 7 + ****** + 后 2（边界）', () => {
    expect(maskApiKey('pmcp_ab')).toBe('pmcp_a******ab')
  })

  it('短前缀（<8 字符）→ 全显 + ****（非 ******）', () => {
    expect(maskApiKey('pmcp')).toBe('pmcp****')
  })

  it('空字符串 → 返回 "—"（非空串）', () => {
    expect(maskApiKey('')).toBe('—')
  })

  it('null → 返回 "—"（防御性处理）', () => {
    expect(maskApiKey(null)).toBe('—')
  })

  it('undefined → 返回 "—"（防御性处理）', () => {
    expect(maskApiKey(undefined)).toBe('—')
  })

  it('只有 1 字符 → 全显 + ****', () => {
    expect(maskApiKey('p')).toBe('p****')
  })

  it('只有 7 字符 → 全显 + ****（边界，< 8 走 else 分支）', () => {
    expect(maskApiKey('pmcp_a')).toBe('pmcp_a****')
  })
})
