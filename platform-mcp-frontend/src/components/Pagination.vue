<script setup lang="ts">
import { computed, ref } from "vue"

const props = withDefaults(defineProps<{
  total: number
  page: number
  pageSize: number
  pageSizes?: number[]
}>(), {
  pageSizes: () => [5, 10, 20, 50],
})

const emit = defineEmits<{
  "update:page": [n: number]
  "update:pageSize": [n: number]
  change: []
}>()

const jumpInput = ref("")

const totalPages = computed(() => {
  if (props.total <= 0) return 1
  return Math.ceil(props.total / props.pageSize)
})

// 折叠页码：始终显示 1、N，当前页前后 2 个
const pageList = computed<(number | string)[]>(() => {
  const n = totalPages.value
  const cur = props.page
  if (n <= 7) return Array.from({ length: n }, (_, i) => i + 1)
  const out: (number | string)[] = [1]
  const start = Math.max(2, cur - 1)
  const end = Math.min(n - 1, cur + 1)
  if (start > 2) out.push("…")
  for (let i = start; i <= end; i++) out.push(i)
  if (end < n - 1) out.push("…")
  out.push(n)
  return out
})

function go(p: number) {
  if (p < 1 || p > totalPages.value || p === props.page) return
  emit("update:page", p)
  emit("change")
}

function changeSize(e: Event) {
  const sz = Number((e.target as HTMLSelectElement).value)
  emit("update:pageSize", sz)
  emit("update:page", 1)
  emit("change")
}

function doJump() {
  const n = parseInt(jumpInput.value, 10)
  if (!Number.isNaN(n)) {
    go(n)
    jumpInput.value = ""
  }
}
</script>

<template>
  <div class="pagination">
    <div class="pagination-left">
      <span>每页</span>
      <select class="page-size-select" :value="pageSize" @change="changeSize">
        <option v-for="s in pageSizes" :key="s" :value="s">{{ s }}</option>
      </select>
      <span>条 · 共 {{ total }} 条</span>
    </div>
    <div class="pagination-right">
      <button class="pg-btn" :disabled="page <= 1" @click="go(1)" title="首页">«</button>
      <button class="pg-btn" :disabled="page <= 1" @click="go(page - 1)" title="上一页">‹</button>
      <template v-for="(p, i) in pageList" :key="i">
        <span v-if="p === '…'" class="pg-ellipsis">…</span>
        <button
          v-else
          class="pg-btn"
          :class="{ active: p === page }"
          @click="go(p as number)"
        >{{ p }}</button>
      </template>
      <button class="pg-btn" :disabled="page >= totalPages" @click="go(page + 1)" title="下一页">›</button>
      <button class="pg-btn" :disabled="page >= totalPages" @click="go(totalPages)" title="末页">»</button>
      <span class="pg-jump">
        跳转到
        <input
          v-model="jumpInput"
          class="pg-jump-input"
          type="number"
          :min="1"
          :max="totalPages"
          @keyup.enter="doJump"
        />
        <button class="pg-btn pg-go" @click="doJump">GO</button>
      </span>
    </div>
  </div>
</template>

<style scoped>
.pagination {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 0 4px;
  font-size: 13px;
  color: var(--color-text-secondary);
}
.pagination-left { display: flex; align-items: center; gap: 6px; }
.pagination-right { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.page-size-select {
  height: 28px;
  padding: 0 6px;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: var(--color-surface);
  color: var(--color-text);
  font-size: 13px;
}
.pg-btn {
  min-width: 28px;
  height: 28px;
  padding: 0 6px;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: var(--color-surface);
  color: var(--color-text);
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s;
}
.pg-btn:hover:not(:disabled):not(.active) {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
.pg-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.pg-btn.active {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #fff;
}
.pg-ellipsis {
  min-width: 28px;
  text-align: center;
  color: var(--color-text-muted);
}
.pg-jump {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: 8px;
}
.pg-jump-input {
  width: 48px;
  height: 28px;
  padding: 0 4px;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: var(--color-surface);
  color: var(--color-text);
  text-align: center;
  font-size: 13px;
}
.pg-go { min-width: 36px; }
</style>
