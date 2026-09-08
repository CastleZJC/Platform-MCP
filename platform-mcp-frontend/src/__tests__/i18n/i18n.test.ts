/** i18n 资源齐备性守卫 — V3.0 M1 发布前检查（2026-09-03）
 *
 * 防回归目标：新增语言（如四期日语）或增删键时，本测试强制所有语言包键位 1:1 镜像，
 * 杜绝“某语言缺键回退默认语言”悄悄上线。
 * 同功能同义同出处（V3.0 起）：同一功能同一词义的文案必须单一出处（通常 common 段），
 * 跨段同名同值键禁止新增；存量白名单键逐步收敛（新增键不得进入白名单）。
 */
import { describe, expect, it } from "vitest"
import { i18n, LOCALE_OPTIONS, SUPPORTED_LOCALES } from "../../i18n/index"

// 语言包清单自动发现（与 src/i18n/index.ts 同规则 glob）：新增语言零登记即纳入全部守卫
const modules = import.meta.glob(["../../i18n/*.ts", "!../../i18n/index.ts"], { eager: true }) as Record<
  string,
  { default: unknown; nativeName?: string }
>
const PACKS: Record<string, unknown> = Object.fromEntries(
  Object.entries(modules).map(([p, m]) => [p.replace(/^.*\//, "").replace(/\.ts$/, ""), m.default]),
)

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

  it("LOCALE_OPTIONS 与 SUPPORTED_LOCALES 一致（自语言包自动派生，新增语言零登记）", () => {
    expect(LOCALE_OPTIONS.map((o) => o.value)).toEqual([...SUPPORTED_LOCALES])
    expect(SUPPORTED_LOCALES[0]).toBe("zh-CN") // 默认语言置首
    // nativeName 必须具名导出于语言包（缺省回退文件路径即缺陷）
    for (const o of LOCALE_OPTIONS) {
      expect(o.nativeName).toBeTruthy()
      expect(o.nativeName).not.toContain(".ts")
    }
  })

  it("所有语言包与 zh-CN 键位 1:1 镜像（双向无缺键）", () => {
    const zh = new Set(flatten(PACKS["zh-CN"]))
    for (const [locale, pack] of Object.entries(PACKS)) {
      if (locale === "zh-CN") continue
      const keys = new Set(flatten(pack))
      expect([...zh].filter((k) => !keys.has(k)), `${locale} 缺键`).toEqual([])
      expect([...keys].filter((k) => !zh.has(k)), `${locale} 多键`).toEqual([])
    }
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

/** 存量跨段同名同值键白名单（历史遗留，待逐步收敛至 common；新增键禁止进入）
 * 收敛方式：迁移至 common 段后，从各业务段删除同名键并更新页面 t() 引用，
 * 最后从本清单移除键名（守卫自动放行）。
 */
const LEGACY_DUP_KEYS = new Set<string>([
  // 角色标签（layout / user）
  "roleAdmin", "roleDeveloper", "roleUser",
  // 通用表头（audit / config / crypto / datasource / group / plaza / server / skill / user）
  "colEnv", "colGroups", "colHost", "colStatus", "colRemark", "colActions",
  "colOperator", "colType", "colTime", "colCreatedAt", "colDescription",
  // 表单标签/规则/结果（datasource / server）
  "labelEnv", "labelHost", "labelPassword", "labelMaxConcurrent", "labelRemark",
  "ruleHost", "connectSuccess", "connectFailed", "groupDialogTitle",
  // 状态标签与描述标签（config / group）
  "statusEnabled", "statusDisabled", "labelDescription", "updated",
  // 其他（guide / skill）
  "registerDecorator",
])

describe("同功能同义同出处", () => {
  it("跨段同名同值键仅允许白名单存量（新增即 fail）", () => {
    const zh = PACKS["zh-CN"] as Record<string, Record<string, unknown>>
    const byName = new Map<string, Set<string>>()
    for (const [section, entries] of Object.entries(zh)) {
      if (typeof entries !== "object" || entries === null) continue
      for (const k of Object.keys(entries)) {
        if (!byName.has(k)) byName.set(k, new Set())
        byName.get(k)!.add(section)
      }
    }
    const dupes: string[] = []
    for (const [name, sections] of byName) {
      if (sections.size < 2 || LEGACY_DUP_KEYS.has(name)) continue
      const values = new Set([...sections].map((s) => JSON.stringify(zh[s]?.[name])))
      if (values.size === 1) dupes.push(`${name} @ [${[...sections].sort().join(", ")}]`)
    }
    expect(dupes).toEqual([])
  })
})
