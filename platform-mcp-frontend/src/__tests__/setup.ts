import { afterEach } from 'vitest'
import { enableAutoUnmount, flushPromises } from '@vue/test-utils'

// 全局：每个测试结束前先 flush pending render，再 unmount wrapper
// 避免 reactive scope.stop() 后仍有 render 在 queue 中执行导致 setupState 为 undefined
enableAutoUnmount(afterEach)

afterEach(async () => {
  await flushPromises()
})
