<script setup lang="ts">
// V3.0 M1: Element Plus 组件（分页/日期/空状态等）语种随应用 locale 联动
import { computed } from "vue"
import { ElConfigProvider } from "element-plus"
import zhCn from "element-plus/es/locale/lang/zh-cn"
import en from "element-plus/es/locale/lang/en"
import i18n from "@/i18n"

const elLocale = computed(() => (i18n.global.locale.value === "en-US" ? en : zhCn))
</script>

<template>
  <ElConfigProvider :locale="elLocale">
    <router-view />
  </ElConfigProvider>
</template>
