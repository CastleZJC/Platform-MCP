/** i18n 资源齐备性守卫 — V3.0 M1 发布前检查（2026-09-03）
 *
 * 防回归目标：新增语言（如四期日语）或增删键时，本测试强制所有语言包键位 1:1 镜像，
 * 杜绝"某语言缺键回退默认语言"悄悄上线。
 */
import { describe, expect, it } from "vitest"
import enUS from "../../i18n/en-US"
import { i18n, LOCALE_OPTIONS, SUPPORTED_LOCALES } from "../../i18n/index"
import zhCN from "../../i18n/zh-CN"

const PACKS: Record<string, unknown> = {
  "zh-CN": zhCN,
  "en-US": enUS,
}

function flatten(obj: unknown, prefix = ""): string[] {
  if (typeof obj !== "object" || obj === null) {
    return prefix ? [prefix] : []
  }
  return Object.entries(obj).flatMap(([k, v]) => flatten(v, prefix ? `${prefix}.${k}` : k))
}

describe("i18n 资源齐备性", () => {
  it("SUPPORTED_LOCALES 与已注册消息包一致", () => {
    const registered = Object.keys(i18n.global.messages.value)
    expect([...registered].sort()).toEqual([...SUPPORTED_LOCALES].sort())
  })

  it("LOCALE_OPTIONS 与 SUPPORTED_LOCALES 一致（新语言两处同步登记）", () => {
    expect(LOCALE_OPTIONS.map((o) => o.value)).toEqual([...SUPPORTED_LOCALES])
  })

  it("zh-CN ↔ en-US 键位 1:1 镜像（双向无缺键）", () => {
    const zh = new Set(flatten(PACKS["zh-CN"]))
    const en = new Set(flatten(PACKS["en-US"]))
    expect([...zh].filter((k) => !en.has(k))).toEqual([])
    expect([...en].filter((k) => !zh.has(k))).toEqual([])
  })

  it("所有语言包不含空字符串值（空值=未翻译）", () => {
    const empty: string[] = []
    for (const [locale, pack] of Object.entries(PACKS)) {
      for (const key of flatten(pack)) {
        const value = key.split(".").reduce<unknown>((o, k) => (o as Record<string, unknown>)[k], pack)
        if (typeof value === "string" && value === "") empty.push(`${locale}:${key}`)
      }
    }
    expect(empty).toEqual([])
  })

  it("值不含 vue-i18n 保留字符误用（裸 {}、@、|）", () => {
    const bad: string[] = []
    for (const [locale, pack] of Object.entries(PACKS)) {
      for (const key of flatten(pack)) {
        const value = key.split(".").reduce<unknown>((o, k) => (o as Record<string, unknown>)[k], pack)
        if (typeof value === "string" && (/(\{\}|@|\|)/.test(value))) bad.push(`${locale}:${key}`)
      }
    }
    expect(bad).toEqual([])
  })
})
