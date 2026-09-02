import { createI18n } from "vue-i18n"
import zhCN from "./zh-CN"
import enUS from "./en-US"

export const SUPPORTED_LOCALES = ["zh-CN", "en-US"] as const
export type AppLocale = (typeof SUPPORTED_LOCALES)[number]
export const DEFAULT_LOCALE: AppLocale = "zh-CN"
const LOCALE_STORAGE_KEY = "pmcp_locale"

function isSupported(v: string | null | undefined): v is AppLocale {
  return !!v && (SUPPORTED_LOCALES as readonly string[]).includes(v)
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
  messages: {
    "zh-CN": zhCN,
    "en-US": enUS,
  },
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
