import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'

vi.mock('@/utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
}))
vi.mock('@/components/Pagination.vue', () => ({
  default: { template: '<div />' },
}))

import request from '@/utils/request'
import CryptoPage from '@/views/crypto/CryptoPage.vue'

describe('CryptoPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(request.get as any).mockResolvedValue({ data: { items: [], total: 0 } })
    ;(request.post as any).mockResolvedValue({ data: { ciphertext: 'AES:fake', success: true } })
  })

  it('挂载后加载历史', async () => {
    mount(CryptoPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    expect(request.get).toHaveBeenCalledWith('/crypto/history', expect.anything())
  })

  it('handleEncrypt 空明文时 warning', async () => {
    const wrapper = mount(CryptoPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    vm.plaintext = ''
    await vm.handleEncrypt()
    expect(request.post).not.toHaveBeenCalled()
  })

  it('handleEncrypt 有明文时调用 POST /crypto/encrypt', async () => {
    const wrapper = mount(CryptoPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    vm.plaintext = 'secret'
    await vm.handleEncrypt()
    expect(request.post).toHaveBeenCalledWith('/crypto/encrypt', { plaintext: 'secret' })
    expect(vm.ciphertext).toBe('AES:fake')
  })

  it('handleVerify 空密文时 warning', async () => {
    const wrapper = mount(CryptoPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    vm.verifyText = ''
    await vm.handleVerify()
    expect(request.post).not.toHaveBeenCalled()
  })

  it('handleVerify 有密文时调用 POST /crypto/verify', async () => {
    const wrapper = mount(CryptoPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    vm.verifyText = 'AES:fake'
    await vm.handleVerify()
    expect(request.post).toHaveBeenCalledWith('/crypto/verify', { ciphertext: 'AES:fake' })
  })

  it('handleVerify 验证失败时显示错误', async () => {
    ;(request.post as any).mockResolvedValue({ data: { success: false, error: 'mismatch' } })
    const wrapper = mount(CryptoPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    vm.verifyText = 'AES:wrong'
    await vm.handleVerify()
    expect(vm.verifyResult).toContain('验证失败')
    expect(vm.verifyResult).toContain('mismatch')
  })
})
