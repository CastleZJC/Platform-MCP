import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'

vi.mock('@/utils/request', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

vi.mock('@/components/Pagination.vue', () => ({
  default: { template: '<div class="pagination-stub" />' },
}))

import request from '@/utils/request'
import UserPage from '@/views/user/UserPage.vue'

// request 模块被整体 mock，interceptor 不会跑。
// 因此 mock 返回值应是 interceptor 解包后的形态：{code, message, data, trace_id, timestamp}
const mockUsers = {
  code: 0,
  message: 'ok',
  data: {
    items: [
      { id: 1, username: 'admin', nickname: '管理员', role_code: 'admin', status: 1 },
      { id: 2, username: 'alice', nickname: 'Alice', role_code: 'developer', status: 1 },
    ],
    total: 2,
  },
  trace_id: 't1',
  timestamp: Date.now(),
}

describe('UserPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(request.get as any).mockResolvedValue(mockUsers)
    ;(request.post as any).mockResolvedValue({ code: 0, message: 'ok', data: { api_key: 'pmcp_test123' }, trace_id: 't', timestamp: 0 })
    ;(request.put as any).mockResolvedValue({ code: 0, message: 'ok', data: null, trace_id: 't', timestamp: 0 })
  })

  it('挂载后调用 fetchUsers 加载用户列表', async () => {
    mount(UserPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    expect(request.get).toHaveBeenCalledWith('/users', expect.anything())
  })

  it('openCreate 打开新增弹窗并重置表单', async () => {
    const wrapper = mount(UserPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    vm.openCreate()
    await wrapper.vm.$nextTick()
    expect(vm.dialogVisible).toBe(true)
    expect(vm.isEdit).toBe(false)
    expect(vm.form.username).toBe('')
  })

  it('openEdit 填充表单用户数据', async () => {
    const wrapper = mount(UserPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    vm.openEdit({ id: 5, username: 'bob', nickname: 'Bob', role_code: 'admin', status: 1 })
    await wrapper.vm.$nextTick()
    expect(vm.isEdit).toBe(true)
    expect(vm.editId).toBe(5)
    expect(vm.form.username).toBe('bob')
  })

  it('handleSubmit 新增模式调用 POST /users', async () => {
    const wrapper = mount(UserPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    vm.isEdit = false
    vm.form = { username: 'newuser', password: 'pwd', nickname: 'New', role_code: 'developer' }
    await vm.handleSubmit()
    expect(request.post).toHaveBeenCalledWith('/users', expect.any(Object))
  })

  it('handleSubmit 编辑模式调用 PUT /users/:id', async () => {
    const wrapper = mount(UserPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    vm.isEdit = true
    vm.editId = 7
    vm.form = { username: 'x', password: '', nickname: 'Updated', role_code: 'admin' }
    await vm.handleSubmit()
    expect(request.put).toHaveBeenCalledWith('/users/7', expect.any(Object))
  })

  it('handleStatus 调用 PUT /users/:id/status', async () => {
    const wrapper = mount(UserPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    await vm.handleStatus({ id: 3, status: 1 }, 0)
    expect(request.put).toHaveBeenCalledWith('/users/3/status', { status: 0 })
  })

  it('openReset 打开重置密码弹窗', async () => {
    const wrapper = mount(UserPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    vm.openReset({ id: 4 } as any)
    expect(vm.resetVisible).toBe(true)
    expect(vm.resetId).toBe(4)
  })

  it('handleReset 密码不一致时不调用 API', async () => {
    const wrapper = mount(UserPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    vm.resetId = 1
    vm.newPassword = 'a'
    vm.confirmPassword = 'b'
    await vm.handleReset()
    expect(request.post).not.toHaveBeenCalledWith('/users/1/reset-password', expect.anything())
  })

  it('roleTagClass 返回正确的 class', async () => {
    const wrapper = mount(UserPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    expect(vm.roleTagClass('admin')).toBe('tag-danger')
    expect(vm.roleTagClass('developer')).toBe('tag-primary')
  })

  it('roleLabel 返回中文标签', async () => {
    const wrapper = mount(UserPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    expect(vm.roleLabel('admin')).toBe('系统管理员')
    expect(vm.roleLabel('developer')).toBe('开发人员')
  })

  it('maskApiKey 业务场景 — 前缀正确掩码为 pmcp_a******yz', async () => {
    const wrapper = mount(UserPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    expect(vm.maskApiKey('pmcp_abc')).toBe('pmcp_a******bc')
    expect(vm.maskApiKey('pmcp_abcdefghijklmnop')).toBe('pmcp_a******op')
    expect(vm.maskApiKey(null)).toBe('—')
    expect(vm.maskApiKey(undefined)).toBe('—')
    expect(vm.maskApiKey('')).toBe('—')
  })
})
