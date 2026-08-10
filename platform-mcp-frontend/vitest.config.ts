import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    setupFiles: ['src/__tests__/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      include: [
        'src/stores/**/*.ts',
        'src/utils/**/*.ts',
        'src/router/**/*.ts',
        'src/views/**/*.vue',
        'src/components/**/*.vue',
      ],
      exclude: [
        'src/main.ts',
        'src/**/*.d.ts',
      ],
      // 基线门槛（P1-6 第二轮引入 .vue 覆盖率统计）；
      // 随 P1-7 业务场景测试扩充后逐步提升
      thresholds: {
        statements: 50,
        branches: 50,
        functions: 9,
        lines: 50,
      },
    },
  },
})
