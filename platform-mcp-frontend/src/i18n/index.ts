import { createI18n } from "vue-i18n"

export const DEFAULT_LOCALE = "zh-CN"

// 语言包自动装载（import.meta.glob）：新增语言仅新增 ./<locale>.ts（default 消息表 +
// nativeName 具名导出），SUPPORTED_LOCALES / LOCALE_OPTIONS / messages 随之自动扩展，
// 无需改本文件（多语言仅加不改）。
// 消息表两层结构：{ 段名: { 键: 文案 } }，结构上兼容 vue-i18n LocaleMessages
type MessageTable = Record<string, Record<string, string>>

const modules = import.meta.glob(["./*.ts", "!./index.ts"], { eager: true }) as Record<
  string,
  { default: MessageTable; nativeName?: string }
>

interface LocalePack {
  value: string
  messages: MessageTable
  nativeName: string
}

// 默认语言置首，其余按编码排序（选择器选项顺序确定）
const packs: LocalePack[] = Object.entries(modules)
  .map(([path, mod]) => ({
    value: path.replace(/^\.\//, "").replace(/\.ts$/, ""),
    messages: mod.default,
    nativeName: mod.nativeName ?? path,
  }))
  .sort((a, b) =>
    a.value === DEFAULT_LOCALE ? -1 : b.value === DEFAULT_LOCALE ? 1 : a.value.localeCompare(b.value),
  )

export const SUPPORTED_LOCALES: readonly string[] = packs.map((p) => p.value)
export type AppLocale = string

/** 语言选择器选项 — nativeName 为各语言自称（CLDR 惯例：任何界面语言下均显示原名，不随 UI locale 翻译）。 */
export const LOCALE_OPTIONS: ReadonlyArray<{ value: string; nativeName: string }> = packs.map((p) => ({
  value: p.value,
  nativeName: p.nativeName,
}))

const LOCALE_STORAGE_KEY = "pmcp_locale"

function isSupported(v: string | null | undefined): v is AppLocale {
  return !!v && SUPPORTED_LOCALES.includes(v)
}

function detectLocale(): AppLocale {
  const stored = localStorage.getItem(LOCALE_STORAGE_KEY)
  return isSupported(stored) ? stored : DEFAULT_LOCALE
}

export const i18n = createI18n({
  legacy: false,
  locale: detectLocale(),
  fallbackLocale: DEFAULT_LOCALE,
  globalInjection: true,
  messages: Object.fromEntries(packs.map((p) => [p.value, p.messages])),
})

export function setLocale(locale: AppLocale): void {
  i18n.global.locale.value = locale
  localStorage.setItem(LOCALE_STORAGE_KEY, locale)
  document.documentElement.lang = locale
}

export function currentLocale(): AppLocale {
  const v = i18n.global.locale.value
  return isSupported(v) ? v : DEFAULT_LOCALE
}

export default i18n
