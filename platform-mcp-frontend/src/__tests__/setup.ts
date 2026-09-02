import { afterEach } from 'vitest'
import { config, enableAutoUnmount, flushPromises } from '@vue/test-utils'
import i18n from '@/i18n'

// 全局：为所有组件测试注册 i18n 插件（默认 zh-CN，现有中文文案断言保持有效）
config.global.plugins = [...(config.global.plugins ?? []), i18n]

// 全局：每个测试结束前先 flush pending render，再 unmount wrapper
// 避免 reactive scope.stop() 后仍有 render 在 queue 中执行导致 setupState 为 undefined
enableAutoUnmount(afterEach)

afterEach(async () => {
  await flushPromises()
})
