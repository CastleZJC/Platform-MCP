import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'

vi.mock('@/utils/request', () => ({
  default: { get: vi.fn() },
}))
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import request from '@/utils/request'
import McpGuidePage from '@/views/guide/McpGuidePage.vue'

describe('McpGuidePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(request.get as any).mockImplementation((url: string) => {
      if (url === '/guide/config') {
        return Promise.resolve({
          data: {
            dev: { mcpServers: { 'Platform-MCP': { url: 'http://localhost:9000/mcp' } } },
            prod: { mcpServers: { 'Platform-MCP': { url: 'https://prod/mcp' } } },
          },
        })
      }
      if (url === '/guide/tools') {
        return Promise.resolve({
          data: [
            {
              skill_code: 'database',
              skill_name: 'Database Skill',
              description: 'SQL 执行',
              register_method: 'decorator',
              tool_count: 5,
              tools: [
                { tool_name: 'execute_sql_text', display_name: '执行 SQL', description: '...', risk_level: 'LOW' },
              ],
            },
          ],
        })
      }
      if (url === '/guide/usage') {
        return Promise.resolve({
          data: {
            scenarios: [{ title: '查数据', user_says: '帮我查', behavior: '调用 execute_sql_text' }],
            tips: ['先 validate', '注意风险'],
          },
        })
      }
      return Promise.resolve({ data: {} })
    })
  })

  it('挂载后加载 config/tools/usage', async () => {
    mount(McpGuidePage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    expect(request.get).toHaveBeenCalledWith('/guide/config')
    expect(request.get).toHaveBeenCalledWith('/guide/tools')
    expect(request.get).toHaveBeenCalledWith('/guide/usage')
  })

  it('registerMethodLabel 返回中文标签', async () => {
    const wrapper = mount(McpGuidePage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    expect(vm.registerMethodLabel('decorator')).toBe('装饰器注册')
    expect(vm.registerMethodLabel('form')).toBe('页面新增')
    expect(vm.registerMethodLabel('upload')).toBe('源码上传')
    expect(vm.registerMethodLabel(null)).toBe('—')
    expect(vm.registerMethodLabel('unknown')).toBe('unknown')
  })

  it('riskTagClass 按风险等级返回 class', async () => {
    const wrapper = mount(McpGuidePage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const vm: any = wrapper.vm
    expect(vm.riskTagClass('CRITICAL')).toBe('tag-danger')
    expect(vm.riskTagClass('HIGH')).toBe('tag-danger')
    expect(vm.riskTagClass('MEDIUM')).toBe('tag-warning')
    expect(vm.riskTagClass('LOW')).toBe('tag-success')
  })

  it('copyDevConfig 调用 ElMessage.success', async () => {
    const wrapper = mount(McpGuidePage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })
    const vm: any = wrapper.vm
    vm.copyDevConfig()
    expect(writeText).toHaveBeenCalledWith(expect.any(String))
  })

  it('copyProdConfig 调用 ElMessage.success', async () => {
    const wrapper = mount(McpGuidePage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })
    const vm: any = wrapper.vm
    vm.copyProdConfig()
    expect(writeText).toHaveBeenCalledWith(expect.any(String))
  })
})
