/**
 * 极简 Markdown 渲染器（知识库文档正文专用）。
 *
 * 仅覆盖 kb 一病一档文档用到的语法：标题(#~######)、粗体、行内代码、代码块、
 * 无序/有序列表、引用、分隔线、链接、段落；未覆盖的语法按普通文本输出。
 * 所有文本先做 HTML 转义再拼装，防止正文注入。
 */

/** HTML 转义 */
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** 行内语法：`code` / **bold** / [text](url) */
function renderInline(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
}

/**
 * Markdown → HTML 片段（不含 <html>/<body> 等外壳，供 v-html 使用）。
 * @param {string|null} md Markdown 源文本
 * @returns {string} HTML 字符串
 */
export function renderMarkdown(md) {
  if (!md) return ''
  const lines = String(md).replace(/\r\n/g, '\n').split('\n')
  const html = []
  let para = [] // 段落缓冲
  let list = null // { type: 'ul'|'ol', items: [] }
  let inCode = false
  let codeLines = []

  const flushPara = () => {
    if (para.length) {
      html.push(`<p>${renderInline(para.join(' '))}</p>`)
      para = []
    }
  }
  const flushList = () => {
    if (list) {
      html.push(`<${list.type}>${list.items.map((i) => `<li>${renderInline(i)}</li>`).join('')}</${list.type}>`)
      list = null
    }
  }

  for (const line of lines) {
    // 代码块内部：原样收集，直到闭合围栏
    if (inCode) {
      if (/^```/.test(line.trim())) {
        html.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
        inCode = false
        codeLines = []
      } else {
        codeLines.push(line)
      }
      continue
    }

    const t = line.trim()
    if (/^```/.test(t)) {
      flushPara()
      flushList()
      inCode = true
      continue
    }
    if (!t) {
      flushPara()
      flushList()
      continue
    }

    const heading = t.match(/^(#{1,6})\s+(.*)$/)
    if (heading) {
      flushPara()
      flushList()
      const lv = heading[1].length
      html.push(`<h${lv}>${renderInline(heading[2])}</h${lv}>`)
      continue
    }
    if (/^(-{3,}|\*{3,})$/.test(t)) {
      flushPara()
      flushList()
      html.push('<hr/>')
      continue
    }
    const ul = t.match(/^[-*]\s+(.*)$/)
    if (ul) {
      flushPara()
      if (!list || list.type !== 'ul') {
        flushList()
        list = { type: 'ul', items: [] }
      }
      list.items.push(ul[1])
      continue
    }
    const ol = t.match(/^\d+[.、]\s+(.*)$/)
    if (ol) {
      flushPara()
      if (!list || list.type !== 'ol') {
        flushList()
        list = { type: 'ol', items: [] }
      }
      list.items.push(ol[1])
      continue
    }
    const quote = t.match(/^>\s?(.*)$/)
    if (quote) {
      flushPara()
      flushList()
      html.push(`<blockquote>${renderInline(quote[1])}</blockquote>`)
      continue
    }

    flushList()
    para.push(t)
  }

  // 收尾：未闭合代码块按代码输出，再冲刷缓冲
  if (inCode && codeLines.length) {
    html.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
  }
  flushPara()
  flushList()
  return html.join('\n')
}
