<script lang="ts">
/** 公共列表组件 — 全站 data-table 单一出处（V3.0 列表统一，2026-09-07）
 *
 * 列默认等分：table-layout: fixed + colgroup，未指定 width 的列均分剩余宽度；
 * 需要固定列宽时经 column.width 覆盖（如操作列 '280px'）。
 * 单元格自定义渲染：按列 key 具名插槽（#actions="{ row }"），缺省渲染 row[key]（空值 '—'）。
 * 泛型 T：插槽 row 类型随 :rows 推断（页面函数可直接接收具体行类型）。
 */
export interface DataColumn {
  key: string
  label: string
  width?: string
  align?: "left" | "center" | "right"
  cls?: string
}
</script>

<script setup lang="ts" generic="T extends Record<string, any>">
import { computed } from "vue"

const props = withDefaults(defineProps<{
  columns: DataColumn[]
  rows: T[]
  loading?: boolean
  emptyText?: string
  rowKey?: string
  tableClass?: string
}>(), {
  loading: false,
  emptyText: "",
  rowKey: "",
  tableClass: "",
})

const list = computed(() => props.rows || [])

function keyOf(row: T, i: number): string | number {
  if (props.rowKey) {
    const v = row[props.rowKey]
    if (v !== undefined && v !== null) return String(v)
  }
  return i
}
</script>

<template>
  <table class="data-table" :class="tableClass" v-loading="loading">
    <colgroup>
      <col v-for="c in columns" :key="c.key" :style="{ width: c.width || undefined }" />
    </colgroup>
    <thead>
      <tr>
        <th v-for="c in columns" :key="c.key" :style="{ textAlign: c.align }">{{ c.label }}</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="(row, i) in list" :key="keyOf(row, i)">
        <td
          v-for="c in columns" :key="c.key"
          :class="[c.cls, { actions: c.key === 'actions' }]"
          :style="{ textAlign: c.align }"
        >
          <slot :name="c.key" :row="row" :index="i">{{ row[c.key] ?? "—" }}</slot>
        </td>
      </tr>
      <tr v-if="!loading && list.length === 0">
        <td :colspan="columns.length" class="dt-empty">{{ emptyText || "—" }}</td>
      </tr>
    </tbody>
  </table>
</template>

<style scoped>
/* table-layout: fixed 是"列默认等分"的关键：列宽只认 colgroup（未指定 width 的列均分剩余宽度），
   内容不再撑宽列，长值在单元格内自动换行（overflow-wrap） */
table { table-layout: fixed; }
td { overflow-wrap: break-word; }
.dt-empty { text-align: center; color: var(--color-text-secondary); padding: 24px 0; }
</style>
