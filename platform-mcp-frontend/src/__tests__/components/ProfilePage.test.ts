import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'

vi.mock('@/utils/request', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
  ElMessageBox: { confirm: vi.fn().mockResolvedValue('confirm') },
}))

import request from '@/utils/request'
import ProfilePage from '@/views/profile/ProfilePage.vue'
import { useUserStore } from '@/stores/user'

describe('ProfilePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(request.get as any).mockImplementation((url: string) => {
      if (url === '/profile') return Promise.resolve({ data: { nickname: 'Admin', email: 'a@b.c' } })
      if (url === '/api-keys') return Promise.resolve({ data: [{ id: 1, key_prefix: 'pmcp_abc', status: 1 }] })
      if (url.startsWith('/api-keys/full/')) return Promise.resolve({ data: { full_key: 'pmcp_plaintext_key' } })
      return Promise.resolve({ data: {} })
    })
    ;(request.put as any).mockResolvedValue({ data: { code: 0 } })
    ;(request.post as any).mockResolvedValue({ data: { code: 0 } })
  })

  it('挂载后加载 profile 和 api_key', async () => {
    mount(ProfilePage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    expect(request.get).toHaveBeenCalledWith('/profile')
    expect(request.get).toHaveBeenCalledWith('/api-keys')
  })

  it('handleSaveProfile 调用 PUT /profile', async () => {
    const wrapper = mount(ProfilePage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    vm.nickname = 'NewName'
    vm.email = 'new@x.com'
    await vm.handleSaveProfile()
    expect(request.put).toHaveBeenCalledWith('/profile', { nickname: 'NewName', email: 'new@x.com' })
  })

  it('handleChangePassword 密码一致时调用 POST', async () => {
    const wrapper = mount(ProfilePage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    vm.oldPassword = 'old'
    vm.newPassword = 'new'
    vm.confirmPassword = 'new'
    await vm.handleChangePassword()
    expect(request.post).toHaveBeenCalledWith('/profile/change-password', {
      old_password: 'old', new_password: 'new',
    })
  })

  it('handleChangePassword 密码不一致时不调用 API', async () => {
    const wrapper = mount(ProfilePage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    vm.oldPassword = 'old'
    vm.newPassword = 'a'
    vm.confirmPassword = 'b'
    await vm.handleChangePassword()
    expect(request.post).not.toHaveBeenCalled()
  })

  it('toggleApiKey 未登录时不请求 /api-keys/full/', async () => {
    const pinia = createPinia()
    const wrapper = mount(ProfilePage, { global: { plugins: [pinia] } })
    await flushPromises()
    const vm: any = wrapper.vm
    const userStore = useUserStore(pinia)
    userStore.user = null as any
    vm.keyVisible = false
    await vm.toggleApiKey()
    const fullCalls = (request.get as any).mock.calls.filter((c: any[]) => c[0].startsWith('/api-keys/full/'))
    expect(fullCalls.length).toBe(0)
  })

  it('toggleApiKey keyVisible=true 时关闭', async () => {
    const wrapper = mount(ProfilePage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    vm.keyVisible = true
    await vm.toggleApiKey()
    expect(vm.keyVisible).toBe(false)
  })

  it('loadApiKey 无活跃 key 时不设置 apiKeyId', async () => {
    ;(request.get as any).mockImplementation((url: string) => {
      if (url === '/profile') return Promise.resolve({ data: {} })
      if (url === '/api-keys') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: {} })
    })
    const wrapper = mount(ProfilePage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    expect(vm.apiKeyId).toBe(0)
  })
})
