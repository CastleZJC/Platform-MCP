/**
 * 复制文本到剪贴板，HTTP context 兜底。
 *
 * navigator.clipboard 仅在 secure context（HTTPS 或 localhost）可用；
 * 生产环境用 HTTP 部署时 navigator.clipboard 为 undefined，必须降级到
 * document.execCommand('copy')（已 deprecated 但所有浏览器仍支持）。
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  // 优先 Clipboard API（HTTPS / localhost / 测试 mock 都会注入 navigator.clipboard）
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // fallthrough 到兜底
    }
  }
  // 兜底：HTTP context 下 navigator.clipboard 为 undefined，走 deprecated execCommand
  try {
    const ta = document.createElement("textarea")
    ta.value = text
    ta.style.position = "fixed"
    ta.style.left = "-9999px"
    ta.setAttribute("readonly", "")
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand("copy")
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
