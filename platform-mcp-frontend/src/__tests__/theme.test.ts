/** 5.5.3 CSS variables verification */
import { describe, it, expect } from "vitest"
import { readFileSync } from "fs"
import { resolve } from "path"

describe("CSS Variables", () => {
  it("variables.css has primary color defined", () => {
    const content = readFileSync(resolve(__dirname, "../styles/variables.css"), "utf-8")
    expect(content).toContain("--color-primary")
    expect(content).toContain("--color-surface")
  })

  it("global.css imports variables", () => {
    const content = readFileSync(resolve(__dirname, "../styles/global.css"), "utf-8")
    expect(content).toContain("variables")
  })

  it("dark theme has different colors", () => {
    const content = readFileSync(resolve(__dirname, "../styles/variables.css"), "utf-8")
    expect(content).toContain("[data-theme=\"dark\"]")
  })
})
