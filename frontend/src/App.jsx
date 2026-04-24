import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './App.css'

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const EMPTY_MSG = '你好呀！我是福大灵犀，你可以向我提问关于福州大学的任何问题，也可以查询你的成绩和课表哦～'
const AUTO_SCROLL_THRESHOLD = 80
const THINKING_INDICATOR_DELAY = 1000
const THINKING_STORAGE_KEY = 'fzu_thinking_enabled'

const TOOL_ICONS = {
  retrieve: '📚',
  bocha_websearch_tool: '🌐',
  query_user_memory: '🧠',
  save_user_memory: '💾',
  delete_user_memory: '🗑️',
  query_grades: '📊',
  query_gpa_ranking: '📈',
  query_credit_statistics: '🎓',
  query_courses: '📅',
  query_course_selection: '🧾',
  select_course: '✅',
  query_exam_rooms: '🏫',
  query_student_info: '👤',
  query_exam_scores: '📝',
  query_academic_calendar: '🗓️',
  query_cultivate_plan: '🧭',
}

const SEARCH_RESULT_TOOL_NAMES = new Set(['retrieve', 'bocha_websearch_tool'])
const EDUCATIONAL_TOOL_NAMES = new Set([
  'query_grades',
  'query_gpa_ranking',
  'query_credit_statistics',
  'query_courses',
  'query_course_selection',
  'select_course',
  'query_exam_rooms',
  'query_student_info',
  'query_exam_scores',
  'query_academic_calendar',
  'query_cultivate_plan',
])

const FALLBACK_HEX = Array.from({ length: 256 }, (_, index) => index.toString(16).padStart(2, '0'))

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const fmt = (v) =>
  v
    ? new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric' }).format(
        new Date(v),
      )
    : ''

const createUuid = () => {
  const cryptoApi = globalThis.crypto
  if (typeof cryptoApi?.randomUUID === 'function') return cryptoApi.randomUUID()

  if (typeof cryptoApi?.getRandomValues === 'function') {
    const bytes = new Uint8Array(16)
    cryptoApi.getRandomValues(bytes)
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    return `${FALLBACK_HEX[bytes[0]]}${FALLBACK_HEX[bytes[1]]}${FALLBACK_HEX[bytes[2]]}${FALLBACK_HEX[bytes[3]]}-${FALLBACK_HEX[bytes[4]]}${FALLBACK_HEX[bytes[5]]}-${FALLBACK_HEX[bytes[6]]}${FALLBACK_HEX[bytes[7]]}-${FALLBACK_HEX[bytes[8]]}${FALLBACK_HEX[bytes[9]]}-${FALLBACK_HEX[bytes[10]]}${FALLBACK_HEX[bytes[11]]}${FALLBACK_HEX[bytes[12]]}${FALLBACK_HEX[bytes[13]]}${FALLBACK_HEX[bytes[14]]}${FALLBACK_HEX[bytes[15]]}`
  }

  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}`
}

const stripMarkdown = (value = '') =>
  String(value)
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^>\s?/gm, '')
    .replace(/[#*_~>-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

const splitMarkdownTableLine = (line = '') =>
  String(line)
    .trim()
    .replace(/^\|\s*/, '')
    .replace(/\s*\|$/, '')
    .split(/(?<!\\)\|/)
    .map((cell) => cell.trim())

const isMarkdownTableLine = (line = '') => {
  const trimmed = String(line).trim()
  return trimmed.startsWith('|') && splitMarkdownTableLine(trimmed).length > 1
}

const isMarkdownSeparatorLine = (cells = []) =>
  cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, '')))

const formatMarkdownTableRow = (cells = []) =>
  `| ${cells.map((cell) => String(cell ?? '').trim() || '—').join(' | ')} |`

const normalizeMarkdownTableBlock = (lines = []) => {
  if (lines.length < 2) return lines

  const parsedRows = lines.map(splitMarkdownTableLine)
  const columnCount = Math.max(...parsedRows.map((row) => row.length))
  if (columnCount < 2) return lines

  const normalizeCells = (cells = [], filler = '—') =>
    Array.from({ length: columnCount }, (_, index) => {
      const value = String(cells[index] ?? '').trim()
      return value || filler
    })

  const normalizedLines = [formatMarkdownTableRow(normalizeCells(parsedRows[0]))]
  const secondRow = parsedRows[1]

  if (isMarkdownSeparatorLine(secondRow)) {
    normalizedLines.push(formatMarkdownTableRow(normalizeCells(secondRow, '---').map(() => '---')))
    for (const row of parsedRows.slice(2)) {
      normalizedLines.push(formatMarkdownTableRow(normalizeCells(row)))
    }
    return normalizedLines
  }

  normalizedLines.push(formatMarkdownTableRow(Array(columnCount).fill('---')))
  for (const row of parsedRows.slice(1)) {
    normalizedLines.push(formatMarkdownTableRow(normalizeCells(row)))
  }
  return normalizedLines
}

const normalizeMarkdownTables = (content = '') => {
  const lines = String(content).split('\n')
  const normalized = []
  let tableBlock = []
  let fenceMarker = null

  const flushTableBlock = () => {
    if (tableBlock.length === 0) return
    normalized.push(...normalizeMarkdownTableBlock(tableBlock))
    tableBlock = []
  }

  for (const line of lines) {
    const trimmed = line.trim()
    const fenceMatch = trimmed.match(/^(```+|~~~+)/)

    if (fenceMatch) {
      flushTableBlock()
      const marker = fenceMatch[1][0]
      fenceMarker = fenceMarker === marker ? null : marker
      normalized.push(line)
      continue
    }

    if (fenceMarker) {
      flushTableBlock()
      normalized.push(line)
      continue
    }

    if (isMarkdownTableLine(line)) {
      tableBlock.push(line)
      continue
    }

    flushTableBlock()
    normalized.push(line)
  }

  flushTableBlock()
  return normalized.join('\n')
}

const toDomIdFragment = (value = '') => String(value).trim().replace(/[^a-zA-Z0-9_-]+/g, '-')

const getCitationAnchorId = (messageId, toolKey, citationId) =>
  `citation-${toDomIdFragment(messageId)}-${toDomIdFragment(toolKey)}-${toDomIdFragment(citationId)}`

const buildCitationLinkMap = (messageId, parts = []) => {
  const citationMap = {}

  for (const part of parts) {
    if (part?.type !== 'tool' || !SEARCH_RESULT_TOOL_NAMES.has(part.tool_name)) continue
    const items = Array.isArray(part?.data?.items) ? part.data.items : []
    const toolKey = part.tool_id ?? part.tool_name

    for (const item of items) {
      const citationId = String(item?.citation_id ?? '').trim()
      if (!citationId || citationMap[citationId]) continue
      citationMap[citationId] = `#${getCitationAnchorId(messageId, toolKey, citationId)}`
    }
  }

  return citationMap
}

const linkifyCitationReferences = (content = '', citationMap = {}) =>
  String(content).replace(/\[(\d+)\](?!\()/g, (match, citationId) => {
    const href = citationMap[citationId]
    return href ? `[[${citationId}]](${href})` : match
  })

const scrollToCitation = (href = '') => {
  if (!href.startsWith('#') || typeof document === 'undefined') return
  const target = document.getElementById(href.slice(1))
  if (!target) return
  target.scrollIntoView({ behavior: 'smooth', block: 'center' })
  target.classList.add('tool-citation-item--targeted')
  if (typeof window !== 'undefined') {
    window.setTimeout(() => target.classList.remove('tool-citation-item--targeted'), 1800)
  }
}

const compactParts = (parts = []) => {
  const normalized = []
  for (const part of parts) {
    if (!part?.type) continue
    if (part.type === 'text') {
      const content = String(part.content ?? '')
      if (!content) continue
      const prev = normalized.at(-1)
      if (prev?.type === 'text') prev.content = `${prev.content}${content}`
      else normalized.push({ type: 'text', content })
      continue
    }
    normalized.push(part)
  }
  return normalized
}

const appendTextPart = (parts = [], delta = '') => {
  if (!delta) return compactParts(parts)
  return compactParts([...parts, { type: 'text', content: delta }])
}

const replaceToolPart = (parts = [], nextPart) =>
  compactParts(parts.map((part) => (part.type === 'tool' && part.tool_id === nextPart.tool_id ? nextPart : part)))

const hasRunningToolPart = (parts = []) =>
  parts.some((part) => part?.type === 'tool' && part.status === 'running')

const creditProgress = (gain, total) => {
  const gainValue = Number.parseFloat(String(gain ?? '').replace(/[^\d.]+/g, ''))
  const totalValue = Number.parseFloat(String(total ?? '').replace(/[^\d.]+/g, ''))
  if (!Number.isFinite(gainValue) || !Number.isFinite(totalValue) || totalValue === 0) return '—'
  const ratio = (gainValue / totalValue) * 100
  return Number.isInteger(ratio) ? `${ratio.toFixed(0)}%` : `${ratio.toFixed(1)}%`
}

const groupGradesBySemester = (rows = []) => {
  const groups = new Map()
  for (const row of rows) {
    const code = row.semester_code ?? row.semester ?? '未知学期'
    const label = row.semester ?? row.semester_code ?? '未知学期'
    if (!groups.has(code)) groups.set(code, { code, label, rows: [] })
    groups.get(code).rows.push(row)
  }
  return Array.from(groups.values()).sort((left, right) => String(right.code).localeCompare(String(left.code)))
}

const draftAssistant = () => ({
  id: `draft-${createUuid()}`,
  role: 'assistant',
  content: '',
  parts: [],
  feedback: null,
  timestamp: new Date().toISOString(),
  isDraft: true,
  showThinkingIndicator: true,
})

const previewText = (messages = [], { skipErrorFallback = true } = {}) => {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    const isErrorFallback = message?.isErrorFallback ?? message?.is_error_fallback ?? false
    if (skipErrorFallback && isErrorFallback) continue
    const content = compactParts(
      message?.parts?.length ? message.parts : message?.content ? [{ type: 'text', content: message.content }] : [],
    )
      .filter((part) => part.type === 'text')
      .map((part) => stripMarkdown(part.content ?? ''))
      .join(' ')
      .trim()
    if (content) return content
  }
  return ''
}

const makeConversationSummary = (conversation) => {
  const messages = conversation.messages ?? []
  const preview = previewText(messages) || previewText(messages, { skipErrorFallback: false })
  return {
    id: conversation.id,
    title: conversation.title,
    model: conversation.model,
    created_at: conversation.created_at,
    updated_at: conversation.updated_at,
    preview: preview.slice(0, 80),
    message_count: messages.length,
  }
}

const conversationMessageCount = (conversation) => {
  if (Number.isFinite(conversation?.message_count)) return Number(conversation.message_count)
  if (Array.isArray(conversation?.messages)) return conversation.messages.length
  return 0
}

const isReusableDraftConversation = (conversation) => Boolean(conversation) && conversation.title === '新对话' && conversationMessageCount(conversation) === 0

const localError = (c = '暂时无法生成回复，请稍后再试。') => ({
  id: `err-${createUuid()}`,
  role: 'assistant',
  content: c,
  parts: [{ type: 'text', content: c }],
  feedback: null,
  timestamp: new Date().toISOString(),
  isErrorFallback: true,
  isLocalOnly: true,
})

const canFeedback = (m) => m.role === 'assistant' && !m.isDraft && !m.isLocalOnly && !m.isErrorFallback
const normMsgs = (msgs = []) =>
  msgs.map((m) => ({
    ...m,
    isErrorFallback: m.isErrorFallback ?? m.is_error_fallback ?? false,
    isLocalOnly: m.isLocalOnly ?? false,
    parts: compactParts(m.parts?.length ? m.parts : m.content ? [{ type: 'text', content: m.content }] : []),
  }))

/* ------------------------------------------------------------------ */
/*  API helpers (inject auth token)                                    */
/* ------------------------------------------------------------------ */

const api = (url, opts = {}) => {
  const headers = { ...(opts.headers || {}) }
  if (opts.body && typeof opts.body === 'string') headers['Content-Type'] = 'application/json'
  return fetch(url, { credentials: opts.credentials ?? 'same-origin', ...opts, headers })
}

/* ================================================================== */
/*  Login Page                                                         */
/* ================================================================== */

function LoginPage({ onLogin }) {
  const [studentId, setStudentId] = useState('')
  const [password, setPassword] = useState('')
  const [studentType, setStudentType] = useState('undergraduate')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!studentId.trim() || !password.trim()) return
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ student_id: studentId.trim(), password: password.trim(), student_type: studentType }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || '登录失败')
      }
      const data = await res.json()
      onLogin(data.user, data.edu_error || '')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <img src="/assets/FZU.png" alt="FZU" className="login-logo" />
          <h1>福大灵犀</h1>
          <p>福州大学智能问答助手</p>
        </div>
        <form className="login-form" onSubmit={handleSubmit}>
          {error && <div className="login-error">{error}</div>}
          <label>
            <span>学号</span>
            <input type="text" value={studentId} onChange={(e) => setStudentId(e.target.value)} placeholder="请输入学号" autoFocus />
          </label>
          <label>
            <span>密码</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="教务系统密码" />
          </label>
          <label>
            <span>学生类型</span>
            <select value={studentType} onChange={(e) => setStudentType(e.target.value)}>
              <option value="undergraduate">本科生</option>
              <option value="graduate" disabled>研究生（暂未开放）</option>
            </select>
          </label>
          <button type="submit" className="login-btn" disabled={loading || !studentId.trim() || !password.trim()}>
            {loading ? '登录中…' : '登 录'}
          </button>
        </form>
        <p className="login-footer">密码仅用于即时教务认证，登录态通过站点安全 Cookie 保存</p>
      </div>
    </div>
  )
}

function EduReloginPanel({ message, studentId, onSubmit }) {
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!password.trim() || loading) return
    setLoading(true)
    setError('')
    try {
      await onSubmit(password.trim())
      setPassword('')
    } catch (err) {
      setError(err.message || '重新连接教务失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="edu-warn edu-warn--interactive">
      <div className="edu-warn-title">{message || '教务登录已过期，请重新连接教务。'}</div>
      <div className="edu-warn-note">重新连接后不会退出当前账号，也不会丢失现有对话。</div>
      <form className="edu-relogin-form" onSubmit={handleSubmit}>
        <label className="edu-relogin-field">
          <span>{studentId ? `当前学号：${studentId}` : '教务密码'}</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="请输入教务密码"
            autoComplete="current-password"
          />
        </label>
        <button type="submit" className="edu-relogin-btn" disabled={loading || !password.trim()}>
          {loading ? '重新连接中…' : '重新连接教务'}
        </button>
      </form>
      {error && <div className="edu-relogin-error">{error}</div>}
    </div>
  )
}

/* ================================================================== */
/*  Grade Table                                                        */
/* ================================================================== */

function GradeTable({ data }) {
  if (!Array.isArray(data) || data.length === 0) return null
  const groups = groupGradesBySemester(data)
  return (
    <div className="grade-groups">
      {groups.map((group, index) => (
        <details key={group.code || `${group.label}-${index}`} className="grade-group" open={groups.length === 1 || index === 0}>
          <summary>
            <span>{group.label}</span>
            <span>{group.rows.length} 门</span>
          </summary>
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>课程</th><th>学分</th><th>成绩</th><th>绩点</th>
                </tr>
              </thead>
              <tbody>
                {group.rows.map((r, rowIndex) => (
                  <tr key={`${group.code}-${r.name}-${rowIndex}`}>
                    <td>{r.name}</td><td>{r.credits}</td><td>{r.score}</td><td>{r.gpa}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ))}
    </div>
  )
}

/* ================================================================== */
/*  Course Table                                                       */
/* ================================================================== */

function CourseTable({ data }) {
  if (!Array.isArray(data) || data.length === 0) return null
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>课程</th><th>教师</th><th>学分</th><th>时间</th><th>地点</th>
          </tr>
        </thead>
        <tbody>
          {data.map((r, i) => (
            <tr key={i}>
              <td>{r.name}</td><td>{r.teacher}</td><td>{r.credits}</td><td>{r.time}</td><td>{r.location}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ================================================================== */
/*  Exam Table                                                         */
/* ================================================================== */

function ExamTable({ data }) {
  if (!Array.isArray(data) || data.length === 0) return null
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr><th>考试</th><th>成绩</th><th>日期</th></tr>
        </thead>
        <tbody>
          {data.map((r, i) => (
            <tr key={i}><td>{r.exam_name}</td><td>{r.score}</td><td>{r.date}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StructuredTable({ headers, rows }) {
  if (!Array.isArray(rows) || rows.length === 0) return null
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => <td key={`${rowIndex}-${cellIndex}`}>{cell || '—'}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function GpaCard({ data }) {
  if (!data || !Array.isArray(data.items) || data.items.length === 0) return null
  return (
    <div className="tool-sections">
      {data.time && <div className="tool-summary">统计时间：{data.time}</div>}
      <StructuredTable headers={['指标', '数值']} rows={data.items.map((item) => [item.type, item.value])} />
    </div>
  )
}

function CreditStatsCard({ data }) {
  if (!data || typeof data !== 'object') return null
  const sections = [
    { title: '主修专业', rows: Array.isArray(data.major) ? data.major : [] },
    { title: '辅修专业', rows: Array.isArray(data.minor) ? data.minor : [] },
  ].filter((section) => section.rows.length > 0)
  if (sections.length === 0) return null

  return (
    <div className="tool-sections">
      {sections.map((section) => (
        <section key={section.title} className="tool-section">
          <div className="tool-section-title">{section.title}</div>
          <StructuredTable
            headers={['类别', '已获', '应修', '完成度']}
            rows={section.rows.map((row) => [row.type, row.gain, row.total, creditProgress(row.gain, row.total)])}
          />
        </section>
      ))}
    </div>
  )
}

function ExamRoomTable({ data }) {
  if (!data || !Array.isArray(data.exams) || data.exams.length === 0) return null
  return (
    <div className="tool-sections">
      <div className="tool-summary">学期：{data.term_label} · {data.exams.length} 场</div>
      <StructuredTable
        headers={['课程', '教师', '日期', '时间', '地点']}
        rows={data.exams.map((exam) => [exam.course_name, exam.teacher, exam.date, exam.time, exam.location])}
      />
    </div>
  )
}

function AcademicCalendarCard({ data }) {
  if (!data || typeof data !== 'object') return null
  const summary = {
    当前学期: data.current_term_label,
    查询学期: data.selected_term_label,
    学期区间: data.start_date && data.end_date ? `${data.start_date} 至 ${data.end_date}` : '',
  }
  const hasEvents = Array.isArray(data.events) && data.events.length > 0
  return (
    <div className="tool-sections">
      <StudentInfoCard data={summary} />
      {hasEvents ? (
        <StructuredTable
          headers={['事件', '开始', '结束']}
          rows={data.events.map((event) => [event.name, event.start_date, event.end_date])}
        />
      ) : (
        <div className="tool-summary">该学期暂无可展示的校历事件</div>
      )}
    </div>
  )
}

const normalizeCultivatePlanText = (value = '') => String(value ?? '').replace(/\s+/g, ' ').trim()

const normalizeCultivatePlanKey = (value = '') => normalizeCultivatePlanText(value).replace(/\s+/g, '')

const buildCultivatePlanTable = (table = {}, fallbackTitle = '') => {
  const headers = Array.isArray(table.headers) && table.headers.length > 0
    ? table.headers.map((header, headerIndex) => normalizeCultivatePlanText(header) || `列${headerIndex + 1}`)
    : []
  const rows = Array.isArray(table.rows)
    ? table.rows
        .map((row) => (Array.isArray(row) ? row.map((cell) => normalizeCultivatePlanText(cell) || '—') : []))
        .filter((row) => row.length > 0)
    : []
  if (headers.length < 2 || rows.length === 0) return null
  return {
    title: normalizeCultivatePlanText(table.title) || normalizeCultivatePlanText(fallbackTitle),
    headers,
    rows,
  }
}

const buildCultivatePlanChapter = (chapter = {}) => {
  const title = normalizeCultivatePlanText(chapter.title)
  const paragraphs = Array.isArray(chapter.paragraphs)
    ? chapter.paragraphs.map((paragraph) => normalizeCultivatePlanText(paragraph)).filter(Boolean)
    : []
  const items = Array.isArray(chapter.items)
    ? chapter.items
        .map((item) => ({
          title: normalizeCultivatePlanText(item?.title),
          content: normalizeCultivatePlanText(item?.content),
        }))
        .filter((item) => item.title || item.content)
    : []
  const tables = Array.isArray(chapter.tables)
    ? chapter.tables
        .map((table) => buildCultivatePlanTable(table, title))
        .filter(Boolean)
    : []

  if (!title && paragraphs.length === 0 && items.length === 0 && tables.length === 0) return null

  return {
    id: chapter.id || title,
    title,
    level: Number(chapter.level || 1),
    paragraphs,
    items,
    tables,
    matchedItemCount: Number(chapter.matched_item_count || 0),
    isPartialMatch: Boolean(chapter.is_partial_match),
  }
}

function CultivatePlanOutline({ outline }) {
  const visibleOutline = Array.isArray(outline) ? outline : []

  return (
    <div className="cultivate-plan-outline">
      {visibleOutline.map((entry, index) => {
        const title = normalizeCultivatePlanText(entry?.title)
        if (!title) return null

        const meta = []
        if (Number(entry?.item_count) > 0) meta.push(`${entry.item_count} 个子项`)
        if (Number(entry?.table_count) > 0) meta.push(`${entry.table_count} 张表`)
        if (Number(entry?.table_count) === 0 && Number(entry?.paragraph_count) > 0) meta.push(`${entry.paragraph_count} 段说明`)

        return (
          <div
            key={`${title}-${index}`}
            className="cultivate-plan-outline-row"
            style={{ '--plan-level': Math.max(0, Number(entry?.level || 1) - 1) }}
          >
            <span className="cultivate-plan-outline-marker">•</span>
            <span className="cultivate-plan-outline-text">{meta.length > 0 ? `${title} · ${meta.join(' / ')}` : title}</span>
          </div>
        )
      })}
    </div>
  )
}

function CultivatePlanChapterSection({ chapter }) {
  if (!chapter) return null

  const showTableTitle = (table, tableIndex) =>
    chapter.tables.length > 1 || tableIndex > 0 || normalizeCultivatePlanKey(table.title) !== normalizeCultivatePlanKey(chapter.title)

  return (
    <section className="selection-category cultivate-plan-section">
      <div className="selection-category-header">
        <div className="tool-section-title">{chapter.title || '命中章节'}</div>
        <div className="cultivate-plan-meta">
          {chapter.isPartialMatch && chapter.matchedItemCount > 0 && <span className="cultivate-plan-pill">命中 {chapter.matchedItemCount} 个子项</span>}
          {chapter.tables.length > 0 && <span className="cultivate-plan-pill">{chapter.tables.length} 张表</span>}
        </div>
      </div>

      {chapter.paragraphs.map((paragraph, index) => (
        <div key={`${chapter.id}-paragraph-${index}`} className="selection-note cultivate-plan-note">{paragraph}</div>
      ))}

      {chapter.items.length > 0 && (
        <div className="cultivate-plan-items">
          {chapter.items.map((item, index) => (
            <div key={`${chapter.id}-item-${item.title || index}`} className="cultivate-plan-item">
              {item.title && <div className="cultivate-plan-item-title">{item.title}</div>}
              {item.content && <div className="cultivate-plan-item-content">{item.content}</div>}
            </div>
          ))}
        </div>
      )}

      {chapter.tables.map((table, index) => (
        <section key={`${chapter.id}-table-${table.title || index}`} className="tool-section">
          {showTableTitle(table, index) && table.title && <div className="tool-section-title">{table.title}</div>}
          <StructuredTable headers={table.headers} rows={table.rows} />
        </section>
      ))}
    </section>
  )
}

function CultivatePlanCard({ data }) {
  if (!data || typeof data !== 'object') return null
  const summary = Object.fromEntries(
    Object.entries({
      年级: data.grade,
      学院: data.college,
      专业: data.major,
      页面: data.title,
    }).filter(([, value]) => normalizeCultivatePlanText(value)),
  )

  const documentTitle = normalizeCultivatePlanText(data.document_title)
  const query = normalizeCultivatePlanText(data.query)
  const outline = Array.isArray(data.outline) ? data.outline : []
  const textBlocks = Array.isArray(data.text_blocks)
    ? data.text_blocks.map((block) => normalizeCultivatePlanText(block)).filter(Boolean)
    : []
  const sections = Array.isArray(data.sections)
    ? data.sections
        .map((section) => buildCultivatePlanTable(section, section?.title))
        .filter(Boolean)
    : []

  const explicitMatches = Array.isArray(data.matched_results)
    ? data.matched_results.map((chapter) => buildCultivatePlanChapter(chapter)).filter(Boolean)
    : []
  const chapters = Array.isArray(data.chapters)
    ? data.chapters.map((chapter) => buildCultivatePlanChapter(chapter)).filter(Boolean)
    : []
  const matchedIds = new Set(
    (Array.isArray(data.matched_chapter_ids) ? data.matched_chapter_ids : [])
      .map((value) => normalizeCultivatePlanText(value))
      .filter(Boolean),
  )
  const matchedTitles = new Set(
    (Array.isArray(data.matched_titles) ? data.matched_titles : [])
      .map((value) => normalizeCultivatePlanKey(value))
      .filter(Boolean),
  )

  const focusedChapters = explicitMatches.length > 0
    ? explicitMatches
    : chapters.filter((chapter) => {
        const titleKey = normalizeCultivatePlanKey(chapter.title)
        return matchedIds.has(chapter.id) || (titleKey && matchedTitles.has(titleKey))
      })

  const hasFocusedChapters = focusedChapters.length > 0
  const rawSectionCount = sections.length
  const rawTextCount = textBlocks.length

  return (
    <div className="tool-sections">
      <StudentInfoCard data={summary} />
      {documentTitle && <div className="tool-summary">文档：{documentTitle}</div>}

      {hasFocusedChapters ? (
        <>
          <div className="tool-summary">{query ? `已定位到和“${query}”相关的 ${focusedChapters.length} 个章节` : `已定位到 ${focusedChapters.length} 个章节`}</div>
          {focusedChapters.map((chapter) => (
            <CultivatePlanChapterSection key={chapter.id} chapter={chapter} />
          ))}
        </>
      ) : outline.length > 0 ? (
        <section className="selection-category cultivate-plan-section">
          <div className="tool-section-title">章节索引</div>
          <div className="tool-summary">
            {query ? `没有直接命中“${query}”，先给你看整份培养方案的结构索引。` : '下面是按章节整理后的培养方案结构。'}
          </div>
          <CultivatePlanOutline outline={outline} />
        </section>
      ) : null}

      {(rawTextCount > 0 || rawSectionCount > 0) && (
        <details className="grade-group cultivate-plan-details">
          <summary>
            <span>查看完整提取结果</span>
            <span>{rawTextCount} 段正文 · {rawSectionCount} 张表</span>
          </summary>
          <div className="tool-sections cultivate-plan-details-body">
            {textBlocks.map((block, index) => (
              <div key={`${block}-${index}`} className="selection-note cultivate-plan-note">{block}</div>
            ))}
            {sections.map((section, index) => (
              <section key={`${section.title || 'plan'}-${index}`} className="tool-section">
                {section.title && <div className="tool-section-title">{section.title}</div>}
                <StructuredTable headers={section.headers} rows={section.rows} />
              </section>
            ))}
          </div>
        </details>
      )}

      {!hasFocusedChapters && outline.length === 0 && rawTextCount === 0 && rawSectionCount === 0 && <div className="tool-summary">暂未提取到可展示的培养方案正文</div>}
    </div>
  )
}

function SelectionStatusBadge({ status }) {
  const labelMap = {
    open: '进行中',
    upcoming: '未开始',
    closed: '已结束',
    unknown: '状态未知',
    success: '成功',
    submitted: '已提交',
    error: '失败',
  }
  return <span className={`selection-status-badge selection-status-badge--${status || 'unknown'}`}>{labelMap[status] || '状态未知'}</span>
}

function CourseSelectionCard({ data }) {
  if (!data || typeof data !== 'object') return null

  if (data.mode === 'submit') {
    const course = data.course || {}
    const summary = {
      类别: data.category_label,
      课程: course.course_name,
      教师: course.teacher,
      学分: course.credits,
      所投积分: data.points,
    }

    return (
      <div className="tool-sections">
        <div className={`selection-result selection-result--${data.status || 'submitted'}`}>
          <div className="selection-category-header">
            <strong>{data.message || '已提交选课请求'}</strong>
            <SelectionStatusBadge status={data.status} />
          </div>
        </div>
        <StudentInfoCard data={Object.fromEntries(Object.entries(summary).filter(([, value]) => value))} />
      </div>
    )
  }

  const categories = Array.isArray(data.categories) ? data.categories : []
  const neededCreditTypes = Array.isArray(data.needed_credit_types) ? data.needed_credit_types : []

  return (
    <div className="tool-sections">
      {neededCreditTypes.length > 0 && (
        <section className="selection-category">
          <div className="tool-section-title">通识缺口</div>
          <StructuredTable
            headers={['类别', '已获', '要求', '还差']}
            rows={neededCreditTypes.map((item) => [item.category, item.earned, item.required, item.missing])}
          />
        </section>
      )}

      {categories.map((category) => (
        <section key={category.key || category.label} className="selection-category">
          <div className="selection-category-header">
            <div className="tool-section-title">{category.label}</div>
            <SelectionStatusBadge status={category.status} />
          </div>
          <div className="selection-meta">
            {category.time_window?.start && category.time_window?.end && <span>时间：{category.time_window.start} 至 {category.time_window.end}</span>}
            <span>候选：{category.candidate_count || 0} 门</span>
            <span>已选：{category.selected_count || 0} 门</span>
          </div>

          {Array.isArray(category.credit_progress) && category.credit_progress.length > 0 && (
            <StructuredTable
              headers={['通识类别', '已获', '要求', '还差']}
              rows={category.credit_progress.map((item) => [item.category, item.earned, item.required, item.missing])}
            />
          )}

          {Array.isArray(category.candidates) && category.candidates.length > 0 && (
            <StructuredTable
              headers={['课程', '教师', '学分', '时间', '类型']}
              rows={category.candidates.map((item) => [item.course_name, item.teacher, item.credits, item.schedule, item.course_type])}
            />
          )}

          {Array.isArray(category.current_courses) && category.current_courses.length > 0 && (
            <StructuredTable
              headers={['课程', '教师', '状态', '学分', '时间']}
              rows={category.current_courses.map((item) => [item.course_name, item.teacher, item.selection_status, item.credits, item.schedule])}
            />
          )}

          {category.status_message && <div className="selection-note">{category.status_message}</div>}
        </section>
      ))}
    </div>
  )
}

function MemoryStatusBadge({ status }) {
  const labelMap = {
    pending_confirmation: '待确认',
    saved: '已保存',
    deleted: '已删除',
    dismissed: '已忽略',
    already_saved: '已存在',
    already_deleted: '已删除',
    not_found: '未找到',
    invalid: '无效',
    unavailable: '不可用',
    error: '失败',
  }

  return <span className={`memory-status-badge memory-status-badge--${status || 'unavailable'}`}>{labelMap[status] || '不可用'}</span>
}

function UserMemoryListCard({ data }) {
  if (!data || typeof data !== 'object') return null
  const items = Array.isArray(data.items) ? data.items : []
  const hasFilter = Boolean(data.query || data.category)

  return (
    <div className="tool-sections">
      <div className="tool-summary">
        {hasFilter
          ? `已检索到 ${items.length} 条匹配的个性化记忆`
          : `最近个性化记忆 ${items.length} 条`}
      </div>
      {items.length > 0 ? (
        <StructuredTable
          headers={['分类', '内容', '备注', '更新时间']}
          rows={items.map((item) => [item.category || '未分类', item.content || '—', item.reason || '—', fmt(item.updated_at) || '—'])}
        />
      ) : (
        <div className="memory-empty-state">{hasFilter ? '没有找到匹配的个性化记忆' : '当前还没有可用的个性化记忆'}</div>
      )}
    </div>
  )
}

function UserMemorySaveCard({ part, data, conversationId, messageId, onAction }) {
  const [pendingAction, setPendingAction] = useState('')
  const [actionError, setActionError] = useState('')
  const status = data?.status || 'pending_confirmation'
  const canAct = status === 'pending_confirmation' && conversationId && messageId && typeof onAction === 'function'
  const savedAt = data?.saved_at || data?.confirmed_at || data?.updated_at || ''

  useEffect(() => {
    setPendingAction('')
    setActionError('')
  }, [status, savedAt])

  const handleAction = async (action) => {
    if (!canAct || pendingAction) return
    setPendingAction(action)
    setActionError('')
    try {
      await onAction(conversationId, messageId, part.tool_id, action)
    } catch (err) {
      setActionError(err.message || '更新记忆状态失败')
      setPendingAction('')
    }
  }

  const summary = Object.fromEntries(
    Object.entries({
      分类: data?.category || '未分类',
      内容: data?.content || '—',
      原因: data?.reason || '—',
    }).filter(([, value]) => value),
  )

  return (
    <div className="tool-sections">
      <section className={`memory-proposal-card memory-proposal-card--${status}`}>
        <div className="selection-category-header">
          <strong>{data?.message || '这条信息值得长期记住'}</strong>
          <MemoryStatusBadge status={status} />
        </div>
        <StudentInfoCard data={summary} />

        {status === 'pending_confirmation' && (
          <>
            <div className="memory-proposal-note">确认后会直接写入你的个性化记忆，后续回答可以按需调用。</div>
            <div className="memory-action-row">
              <button
                type="button"
                className="memory-action-btn memory-action-btn--primary"
                disabled={pendingAction === 'confirm' || pendingAction === 'dismiss'}
                onClick={() => void handleAction('confirm')}
              >
                {pendingAction === 'confirm' ? '保存中…' : '确认保存'}
              </button>
              <button
                type="button"
                className="memory-action-btn memory-action-btn--secondary"
                disabled={pendingAction === 'confirm' || pendingAction === 'dismiss'}
                onClick={() => void handleAction('dismiss')}
              >
                {pendingAction === 'dismiss' ? '处理中…' : '忽略'}
              </button>
            </div>
          </>
        )}

        {status === 'saved' && <div className="memory-proposal-note">{savedAt ? `已于 ${fmt(savedAt)} 保存到个性化记忆` : '这条信息已保存到个性化记忆'}</div>}
        {status === 'dismissed' && <div className="memory-proposal-note">这条记忆建议已忽略，不会被保存。</div>}
        {status === 'already_saved' && <div className="memory-proposal-note">相同内容已存在，无需重复保存。</div>}
        {status === 'invalid' && <div className="memory-proposal-note">这条内容不适合保存为长期个性化记忆。</div>}
        {status === 'unavailable' && <div className="memory-proposal-note">当前无法写入个性化记忆，请稍后重试。</div>}
        {actionError && <div className="memory-proposal-error">{actionError}</div>}
      </section>
    </div>
  )
}

function UserMemoryDeleteCard({ part, data, conversationId, messageId, onAction }) {
  const [pendingAction, setPendingAction] = useState('')
  const [actionError, setActionError] = useState('')
  const status = data?.status || 'pending_confirmation'
  const canAct = status === 'pending_confirmation' && conversationId && messageId && typeof onAction === 'function'
  const items = Array.isArray(data?.items) && data.items.length > 0
    ? data.items
    : Array.isArray(data?.deleted_items)
      ? data.deleted_items
      : []
  const deletedAt = data?.deleted_at || ''
  const missingIds = Array.isArray(data?.missing_ids) ? data.missing_ids : []
  const alreadyDeletedIds = Array.isArray(data?.already_deleted_ids) ? data.already_deleted_ids : []

  useEffect(() => {
    setPendingAction('')
    setActionError('')
  }, [status, deletedAt])

  const handleAction = async (action) => {
    if (!canAct || pendingAction) return
    setPendingAction(action)
    setActionError('')
    try {
      await onAction(conversationId, messageId, part.tool_id, action)
    } catch (err) {
      setActionError(err.message || '更新删除建议失败')
      setPendingAction('')
    }
  }

  return (
    <div className="tool-sections">
      <section className={`memory-proposal-card memory-proposal-card--${status}`}>
        <div className="selection-category-header">
          <strong>{data?.message || `计划删除 ${items.length || data?.memory_ids?.length || 0} 条个性化记忆`}</strong>
          <MemoryStatusBadge status={status} />
        </div>

        {items.length > 0 ? (
          <StructuredTable
            headers={['分类', '内容', '备注', '更新时间']}
            rows={items.map((item) => [item.category || '未分类', item.content || '—', item.reason || '—', fmt(item.updated_at) || '—'])}
          />
        ) : (
          <div className="memory-empty-state">当前没有可展示的目标记忆</div>
        )}

        {data?.reason && <div className="memory-proposal-note">删除原因：{data.reason}</div>}
        {missingIds.length > 0 && <div className="memory-proposal-note">未匹配到的记忆 ID：{missingIds.join('、')}</div>}
        {alreadyDeletedIds.length > 0 && <div className="memory-proposal-note">已删除的记忆 ID：{alreadyDeletedIds.join('、')}</div>}

        {status === 'pending_confirmation' && (
          <>
            <div className="memory-proposal-note">确认后会从你的个性化记忆中删除这些内容，后续回答将不再默认使用。</div>
            <div className="memory-action-row">
              <button
                type="button"
                className="memory-action-btn memory-action-btn--danger"
                disabled={pendingAction === 'confirm' || pendingAction === 'dismiss'}
                onClick={() => void handleAction('confirm')}
              >
                {pendingAction === 'confirm' ? '删除中…' : '确认删除'}
              </button>
              <button
                type="button"
                className="memory-action-btn memory-action-btn--secondary"
                disabled={pendingAction === 'confirm' || pendingAction === 'dismiss'}
                onClick={() => void handleAction('dismiss')}
              >
                {pendingAction === 'dismiss' ? '处理中…' : '忽略'}
              </button>
            </div>
          </>
        )}

        {status === 'deleted' && <div className="memory-proposal-note">{deletedAt ? `已于 ${fmt(deletedAt)} 删除 ${data?.deleted_count || items.length || 0} 条记忆` : '目标记忆已删除'}</div>}
        {status === 'dismissed' && <div className="memory-proposal-note">这次删除建议已忽略，原记忆将继续保留。</div>}
        {status === 'already_deleted' && <div className="memory-proposal-note">这些记忆之前已经删除，无需重复处理。</div>}
        {status === 'not_found' && <div className="memory-proposal-note">没有找到可删除的记忆，可能已经被删除或从未保存。</div>}
        {status === 'invalid' && <div className="memory-proposal-note">删除记忆时需要提供准确的记忆 ID，或提供要删除的精确内容。</div>}
        {status === 'unavailable' && <div className="memory-proposal-note">当前无法删除个性化记忆，请稍后重试。</div>}
        {actionError && <div className="memory-proposal-error">{actionError}</div>}
      </section>
    </div>
  )
}

/* ================================================================== */
/*  Student Info Card                                                  */
/* ================================================================== */

function StudentInfoCard({ data }) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null
  const entries = Object.entries(data)
  if (entries.length === 0) return null
  return (
    <div className="info-card">
      {entries.map(([k, v]) => (
        <div key={k} className="info-row">
          <span className="info-label">{k}</span>
          <span className="info-value">{String(v)}</span>
        </div>
      ))}
    </div>
  )
}

function SearchResultsCard({ part, data, messageId }) {
  const items = Array.isArray(data?.items) ? data.items : []
  if (items.length === 0) return null

  const toolKey = part.tool_id ?? part.tool_name

  return (
    <div className="tool-sections">
      {items.map((item, index) => {
        const citationId = String(item?.citation_id ?? index + 1)
        const anchorId = getCitationAnchorId(messageId, toolKey, citationId)
        const title = item?.title || item?.source_name || item?.url || `结果 ${citationId}`
        const linkLabel = item?.url ? title : `${title}`

        return (
          <section key={anchorId} id={anchorId} className="tool-section tool-citation-item" tabIndex={-1}>
            <div className="tool-citation-row">
              <span className="tool-citation-badge">[{citationId}]</span>
              {item?.url ? (
                <a className="tool-citation-link tool-citation-link--inline" href={item.url} target="_blank" rel="noreferrer">
                  {linkLabel}
                </a>
              ) : (
                <div className="tool-section-title">{linkLabel}</div>
              )}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function MessageMarkdown({ content, citationMap = {} }) {
  const linkedContent = content ? linkifyCitationReferences(content, citationMap) : ''
  const normalizedContent = linkedContent ? normalizeMarkdownTables(linkedContent) : ''
  if (!content) return null

  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href = '', children, ...props }) => {
            if (href.startsWith('#')) {
              return (
                <a
                  {...props}
                  href={href}
                  className="citation-ref"
                  onClick={(event) => {
                    event.preventDefault()
                    scrollToCitation(href)
                  }}
                >
                  {children}
                </a>
              )
            }
            return (
              <a {...props} href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            )
          },
          table: ({ children }) => (
            <div className="markdown-table-wrap">
              <table>{children}</table>
            </div>
          ),
          code: ({ inline, className, children, ...props }) => {
            if (inline) return <code className={className} {...props}>{children}</code>
            return (
              <pre>
                <code className={className} {...props}>{children}</code>
              </pre>
            )
          },
        }}
      >
        {normalizedContent}
      </ReactMarkdown>
    </div>
  )
}

/* ================================================================== */
/*  Tool Card                                                          */
/* ================================================================== */

function ToolCard({ part, conversationId, messageId, onMemoryProposalAction }) {
  const icon = TOOL_ICONS[part.tool_name] || '🔧'
  const isRunning = part.status === 'running'
  const showRawUrls = !['query_cultivate_plan', 'retrieve', 'bocha_websearch_tool'].includes(part.tool_name)
  const [expanded, setExpanded] = useState(() => !EDUCATIONAL_TOOL_NAMES.has(part.tool_name))

  const renderData = () => {
    if (!part.data) return null
    switch (part.tool_name) {
      case 'retrieve':
      case 'bocha_websearch_tool':
        return <SearchResultsCard part={part} data={part.data} messageId={messageId} />
      case 'query_grades':
        return <GradeTable data={part.data} />
      case 'query_gpa_ranking':
        return <GpaCard data={part.data} />
      case 'query_credit_statistics':
        return <CreditStatsCard data={part.data} />
      case 'query_courses':
        return <CourseTable data={part.data} />
      case 'query_course_selection':
      case 'select_course':
        return <CourseSelectionCard data={part.data} />
      case 'query_exam_rooms':
        return <ExamRoomTable data={part.data} />
      case 'query_exam_scores':
        return <ExamTable data={part.data} />
      case 'query_academic_calendar':
        return <AcademicCalendarCard data={part.data} />
      case 'query_cultivate_plan':
        return <CultivatePlanCard data={part.data} />
      case 'query_student_info':
        return <StudentInfoCard data={part.data} />
      case 'query_user_memory':
        return <UserMemoryListCard data={part.data} />
      case 'save_user_memory':
        return (
          <UserMemorySaveCard
            part={part}
            data={part.data}
            conversationId={conversationId}
            messageId={messageId}
            onAction={onMemoryProposalAction}
          />
        )
      case 'delete_user_memory':
        return (
          <UserMemoryDeleteCard
            part={part}
            data={part.data}
            conversationId={conversationId}
            messageId={messageId}
            onAction={onMemoryProposalAction}
          />
        )
      default:
        return null
    }
  }

  return (
    <div className={`tool-card ${isRunning ? 'tool-card--running' : 'tool-card--done'}`}>
      <div className="tool-card-header">
        <div className="tool-card-heading">
          <span className="tool-card-icon">{icon}</span>
          <span className="tool-card-title">{part.status_label}</span>
        </div>
        <div className="tool-card-actions">
          <button
            type="button"
            className="tool-card-toggle"
            onClick={() => setExpanded((value) => !value)}
            aria-expanded={expanded}
          >
            {expanded ? '收起' : '展开'}
          </button>
          {isRunning && <span className="tool-spinner" />}
        </div>
      </div>
      {expanded && (
        <div className="tool-card-body">
          {part.query && <div className="tool-card-query">{part.query}</div>}
          {renderData()}
          {showRawUrls && part.urls?.length > 0 && (
            <div className="tool-links">
              {part.urls.map((u) => (
                <a key={u} href={u} target="_blank" rel="noreferrer">{u}</a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function PendingTitle({ compact = false }) {
  return (
    <span className={`title-skeleton ${compact ? 'title-skeleton--compact' : ''}`} aria-hidden="true">
      <span className="title-skeleton__bar title-skeleton__bar--primary" />
    </span>
  )
}

/* ================================================================== */
/*  Main App                                                           */
/* ================================================================== */

function App() {
  const [user, setUser] = useState(null)
  const [eduError, setEduError] = useState('')
  const [authChecked, setAuthChecked] = useState(false)

  // Chat state
  const [models, setModels] = useState([])
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [msgStore, setMsgStore] = useState({})
  const [input, setInput] = useState('')
  const [selModel, setSelModel] = useState('glm-5.1')
  const [thinkingEnabled, setThinkingEnabled] = useState(() => {
    if (typeof window === 'undefined') return true
    const stored = window.localStorage.getItem(THINKING_STORAGE_KEY)
    return stored === null ? true : stored === '1'
  })
  const [streamingConversations, setStreamingConversations] = useState({})
  const [stopPendingConversations, setStopPendingConversations] = useState({})
  const [pendingTitles, setPendingTitles] = useState({})
  const [error, setError] = useState('')
  const [fbPending, setFbPending] = useState([])
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.localStorage.getItem('fzu_sidebar_collapsed') === '1'
  })
  const msgListRef = useRef(null)
  const shouldAutoScrollRef = useRef(true)
  const draftThinkingTimersRef = useRef(new Map())
  const conversationEventsRef = useRef(null)

  const activeConv = useMemo(() => conversations.find((c) => c.id === activeId) ?? null, [activeId, conversations])
  const activeMsgs = useMemo(() => normMsgs(msgStore[activeId]?.messages ?? []), [activeId, msgStore])
  const userId = user?.user_id ?? ''
  const needsEduRelogin = user?.student_type === 'undergraduate' && !user?.edu_authenticated
  const isActiveConversationStreaming = Boolean(activeId && streamingConversations[activeId])
  const isActiveConversationStopPending = Boolean(activeId && stopPendingConversations[activeId])

  const syncAutoScrollState = useCallback(() => {
    const list = msgListRef.current
    if (!list) return true
    const distanceToBottom = list.scrollHeight - list.scrollTop - list.clientHeight
    const shouldAutoScroll = distanceToBottom <= AUTO_SCROLL_THRESHOLD
    shouldAutoScrollRef.current = shouldAutoScroll
    return shouldAutoScroll
  }, [])

  const scrollMessagesToBottom = useCallback(() => {
    const list = msgListRef.current
    if (!list) return
    list.scrollTop = list.scrollHeight
  }, [])

  const setConversationStreaming = useCallback((cid, nextValue) => {
    if (!cid) return
    setStreamingConversations((prev) => {
      if (nextValue) {
        if (prev[cid]) return prev
        return { ...prev, [cid]: true }
      }
      if (!prev[cid]) return prev
      const next = { ...prev }
      delete next[cid]
      return next
    })
  }, [])

  const setConversationStopPending = useCallback((cid, nextValue) => {
    if (!cid) return
    setStopPendingConversations((prev) => {
      if (nextValue) {
        if (prev[cid]) return prev
        return { ...prev, [cid]: true }
      }
      if (!prev[cid]) return prev
      const next = { ...prev }
      delete next[cid]
      return next
    })
  }, [])

  const setConversationTitlePending = useCallback((cid, nextValue) => {
    if (!cid) return
    setPendingTitles((prev) => {
      if (nextValue) {
        if (prev[cid]) return prev
        return { ...prev, [cid]: true }
      }
      if (!prev[cid]) return prev
      const next = { ...prev }
      delete next[cid]
      return next
    })
  }, [])

  const clearConversationStreamState = useCallback((cid) => {
    if (!cid) return
    setConversationStreaming(cid, false)
    setConversationStopPending(cid, false)
  }, [setConversationStopPending, setConversationStreaming])

  const resetAuthState = useCallback(() => {
    if (conversationEventsRef.current) {
      conversationEventsRef.current.close()
      conversationEventsRef.current = null
    }
    for (const timerId of draftThinkingTimersRef.current.values()) {
      clearTimeout(timerId)
    }
    draftThinkingTimersRef.current.clear()
    setUser(null)
    setEduError('')
    setConversations([])
    setMsgStore({})
    setActiveId(null)
    setStreamingConversations({})
    setStopPendingConversations({})
    setPendingTitles({})
    setError('')
  }, [])

  const refreshAuthState = useCallback(async () => {
    const response = await api('/api/auth/me')
    if (response.status === 401) {
      resetAuthState()
      return null
    }
    if (!response.ok) {
      throw new Error('获取登录状态失败')
    }

    const nextUser = await response.json()
    setUser(nextUser)
    setEduError(nextUser.edu_error || '')
    return nextUser
  }, [resetAuthState])

  const handleMsgListWheel = useCallback((event) => {
    if (event.deltaY < 0) {
      shouldAutoScrollRef.current = false
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('fzu_sidebar_collapsed', sidebarCollapsed ? '1' : '0')
  }, [sidebarCollapsed])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(THINKING_STORAGE_KEY, thinkingEnabled ? '1' : '0')
  }, [thinkingEnabled])

  useEffect(() => {
    if (!shouldAutoScrollRef.current) return
    scrollMessagesToBottom()
  }, [activeMsgs, scrollMessagesToBottom])

  useEffect(() => {
    shouldAutoScrollRef.current = true
  }, [activeId])

  useEffect(() => () => {
    if (conversationEventsRef.current) {
      conversationEventsRef.current.close()
      conversationEventsRef.current = null
    }
    for (const timerId of draftThinkingTimersRef.current.values()) {
      clearTimeout(timerId)
    }
    draftThinkingTimersRef.current.clear()
  }, [])

  // --- Check existing token on mount ---
  useEffect(() => {
    refreshAuthState()
      .then(() => { setAuthChecked(true) })
      .catch(() => { setAuthChecked(true) })
  }, [refreshAuthState])

  // --- Bootstrap after login ---
  useEffect(() => {
    if (!userId) return
    const go = async () => {
      try {
        const [mr, cr] = await Promise.all([api('/api/models'), api('/api/conversations')])
        if (!mr.ok || !cr.ok) throw new Error('初始化失败')
        const [mp, cp] = await Promise.all([mr.json(), cr.json()])
        setModels(mp)
        if (mp.length) setSelModel(mp[0].id)
        setPendingTitles({})
        setConversations(cp)
        if (cp.length) setActiveId(cp[0].id)
      } catch (e) { setError(e.message) }
    }
    go()
  }, [userId])

  const applyConversationSummary = useCallback((cid, summary) => {
    if (!cid || !summary) return
    setMsgStore((state) => {
      const conversation = state[cid]
      if (!conversation) return state
      return {
        ...state,
        [cid]: {
          ...conversation,
          title: summary.title,
          updated_at: summary.updated_at,
          model: summary.model,
        },
      }
    })
    setConversations((prev) => (
      prev.some((item) => item.id === cid)
        ? prev.map((item) => (item.id === cid ? { ...item, ...summary } : item))
        : prev
    ))
    setConversationTitlePending(cid, false)
  }, [setConversationTitlePending])

  useEffect(() => {
    if (!userId || typeof EventSource === 'undefined') return undefined
    const source = new EventSource('/api/conversations/events', { withCredentials: true })
    conversationEventsRef.current = source

    const handleTitle = (event) => {
      try {
        const payload = JSON.parse(event.data)
        const conversation = payload?.conversation
        if (conversation?.id) {
          applyConversationSummary(conversation.id, conversation)
        }
      } catch {
        // Ignore malformed conversation events and allow the stream to continue.
      }
    }

    source.addEventListener('title', handleTitle)

    return () => {
      source.removeEventListener('title', handleTitle)
      source.close()
      if (conversationEventsRef.current === source) {
        conversationEventsRef.current = null
      }
    }
  }, [applyConversationSummary, userId])

  // --- Load conversation messages on select ---
  useEffect(() => {
    if (!activeId || msgStore[activeId]) return
    api(`/api/conversations/${activeId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('加载对话失败'))))
      .then((p) => { setMsgStore((s) => ({ ...s, [activeId]: p })); setSelModel(p.model) })
      .catch((e) => setError(e.message))
  }, [activeId, msgStore])

  // --- Sync model from active conversation ---
  useEffect(() => {
    if (!activeId) return
    const m = msgStore[activeId]?.model ?? activeConv?.model
    if (m && models.some((model) => model.id === m)) {
      setSelModel(m)
      return
    }
    if (models.length > 0) {
      setSelModel(models[0].id)
    }
  }, [activeConv, activeId, models, msgStore])

  // --- Handlers ---
  const handleLogin = useCallback((u, eduErr) => { setUser(u); setEduError(eduErr); setError('') }, [])

  const handleLogout = useCallback(async () => {
    setError('')
    try {
      const response = await api('/api/auth/logout', { method: 'POST' })
      if (response.status === 401) {
        resetAuthState()
        return
      }
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(payload.detail || '退出登录失败，请稍后重试。')
      }
      resetAuthState()
    } catch (err) {
      setError(err.message || '退出登录失败，请稍后重试。')
    }
  }, [resetAuthState])

  const handleEduRelogin = useCallback(async (password) => {
    const response = await api('/api/auth/edu-login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    })
    const payload = await response.json().catch(() => ({}))
    if (response.status === 401) {
      resetAuthState()
      throw new Error('当前登录已失效，请重新登录。')
    }
    if (!response.ok) {
      throw new Error(payload.detail || '重新连接教务失败')
    }
    setUser(payload.user)
    setEduError(payload.edu_error || '')
    return payload.user
  }, [resetAuthState])

  const createConv = useCallback(async () => {
    const activeConversation = activeId ? (msgStore[activeId] ?? activeConv) : null
    if (isReusableDraftConversation(activeConversation)) {
      setActiveId(activeConversation.id)
      return activeConversation
    }

    const reusableSummary = conversations.find((conversation) => isReusableDraftConversation(conversation))
    if (reusableSummary) {
      let reusableConversation = msgStore[reusableSummary.id]
      if (!reusableConversation) {
        const existingResponse = await api(`/api/conversations/${reusableSummary.id}`)
        if (!existingResponse.ok) throw new Error('加载已有新对话失败')
        reusableConversation = await existingResponse.json()
      }
      setConversations((prev) => [makeConversationSummary(reusableConversation), ...prev.filter((item) => item.id !== reusableConversation.id)])
      setMsgStore((prev) => ({ ...prev, [reusableConversation.id]: reusableConversation }))
      setActiveId(reusableConversation.id)
      return reusableConversation
    }

    const r = await api('/api/conversations', { method: 'POST', body: JSON.stringify({ model: selModel }) })
    if (!r.ok) throw new Error('创建对话失败')
    const c = await r.json()
    setConversations((p) => [makeConversationSummary(c), ...p.filter((item) => item.id !== c.id)])
    setMsgStore((p) => ({ ...p, [c.id]: c }))
    setActiveId(c.id)
    return c
  }, [activeConv, activeId, conversations, msgStore, selModel])

  const handleNew = useCallback(async () => { setError(''); try { await createConv() } catch (e) { setError(e.message) } }, [createConv])

  const toggleDesktopSidebar = useCallback(() => {
    setSidebarCollapsed((value) => !value)
  }, [])

  const updateSummary = useCallback((sm) => {
    setConversations((p) => [sm, ...p.filter((c) => c.id !== sm.id)])
  }, [])

  const clearDraftThinkingTimer = useCallback((cid) => {
    const timerId = draftThinkingTimersRef.current.get(cid)
    if (timerId === undefined) return
    clearTimeout(timerId)
    draftThinkingTimersRef.current.delete(cid)
  }, [])

  const handleDelete = useCallback(async (id) => {
    setError('')
    try {
      const r = await api(`/api/conversations/${id}`, { method: 'DELETE' })
      if (!r.ok) throw new Error('删除对话失败')
      clearConversationStreamState(id)
      clearDraftThinkingTimer(id)
      setConversationTitlePending(id, false)
      const nextConversations = conversations.filter((c) => c.id !== id)
      setConversations(nextConversations)
      setMsgStore((p) => { const n = { ...p }; delete n[id]; return n })
      if (activeId === id) setActiveId(nextConversations[0]?.id ?? null)
    } catch (e) { setError(e.message) }
  }, [activeId, clearConversationStreamState, clearDraftThinkingTimer, conversations, setConversationTitlePending])

  const updateDraft = useCallback((cid, fn) => {
    setMsgStore((s) => {
      const cv = s[cid]; if (!cv) return s
      const ms = [...cv.messages]; const last = ms.at(-1)
      if (!last?.isDraft) return s
      ms[ms.length - 1] = fn(last)
      return { ...s, [cid]: { ...cv, messages: ms } }
    })
  }, [])

  const scheduleDraftThinkingIndicator = useCallback((cid) => {
    if (typeof window === 'undefined' || !cid) return
    clearDraftThinkingTimer(cid)
    const timerId = window.setTimeout(() => {
      draftThinkingTimersRef.current.delete(cid)
      updateDraft(cid, (m) => ({ ...m, showThinkingIndicator: true }))
    }, THINKING_INDICATOR_DELAY)
    draftThinkingTimersRef.current.set(cid, timerId)
  }, [clearDraftThinkingTimer, updateDraft])

  const replaceDraft = useCallback((cid, msg, sm, titlePending = false) => {
    clearDraftThinkingTimer(cid)
    setMsgStore((s) => {
      const cv = s[cid]; if (!cv) return s
      const ms = [...cv.messages]
      if (ms.at(-1)?.isDraft) ms[ms.length - 1] = msg; else ms.push(msg)
      return { ...s, [cid]: { ...cv, title: sm.title, updated_at: sm.updated_at, model: sm.model, messages: ms } }
    })
    updateSummary(sm)
    setConversationTitlePending(cid, titlePending)
  }, [clearDraftThinkingTimer, setConversationTitlePending, updateSummary])

  const replaceMessageToolPart = useCallback((cid, mid, part) => {
    setMsgStore((s) => {
      const cv = s[cid]
      if (!cv) return s
      return {
        ...s,
        [cid]: {
          ...cv,
          messages: cv.messages.map((message) => (
            message.id === mid
              ? { ...message, parts: replaceToolPart(message.parts, part) }
              : message
          )),
        },
      }
    })
  }, [])

  const handleMemoryProposalAction = useCallback(async (cid, mid, toolId, action) => {
    const response = await api(`/api/conversations/${cid}/memory-proposals/${toolId}`, {
      method: 'POST',
      body: JSON.stringify({ message_id: mid, action }),
    })
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) {
      throw new Error(payload.detail || '更新记忆建议失败')
    }
    if (payload.part) {
      replaceMessageToolPart(cid, mid, payload.part)
    }
    return payload.part
  }, [replaceMessageToolPart])

  const readSSE = useCallback(async (res, cid) => {
    const reader = res.body.getReader()
    const dec = new TextDecoder()
    let buf = '', ev = 'message'
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const chunks = buf.split('\n\n'); buf = chunks.pop() ?? ''
      for (const ch of chunks) {
        if (!ch.trim()) continue
        let payload = ''
        for (const ln of ch.split('\n')) {
          if (ln.startsWith('event:')) ev = ln.slice(6).trim()
          if (ln.startsWith('data:')) payload += ln.slice(5).trim()
        }
        if (!payload) continue
        const d = JSON.parse(payload)
        if (ev === 'chunk') {
          updateDraft(cid, (m) => {
            const text = m.content + d.delta
            return { ...m, content: text, parts: appendTextPart(m.parts, d.delta), showThinkingIndicator: false }
          })
          scheduleDraftThinkingIndicator(cid)
        }
        if (ev === 'tool_call') {
          updateDraft(cid, (m) => ({
            ...m,
            parts: compactParts([...m.parts, d]),
            showThinkingIndicator: false,
          }))
          scheduleDraftThinkingIndicator(cid)
        }
        if (ev === 'tool_result') {
          updateDraft(cid, (m) => ({
            ...m,
            parts: replaceToolPart(m.parts, d),
            showThinkingIndicator: false,
          }))
          scheduleDraftThinkingIndicator(cid)
        }
        if (ev === 'done') replaceDraft(cid, d.message, d.conversation, d.title_pending === true)
        if (ev === 'title') applyConversationSummary(cid, d.conversation)
        if (ev === 'error') {
          throw Object.assign(new Error(d.message || '生成回复失败'), {
            fallback: d.fallback,
            conversation: d.conversation,
          })
        }
      }
    }
  }, [applyConversationSummary, replaceDraft, scheduleDraftThinkingIndicator, updateDraft])

  const handleStop = useCallback(async () => {
    const cid = activeId
    if (!cid || !streamingConversations[cid] || stopPendingConversations[cid]) return
    setError('')
    setConversationStopPending(cid, true)
    try {
      const response = await api(`/api/conversations/${cid}/stop`, { method: 'POST' })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail || '停止响应失败')
      }
      if (payload.ok === false) {
        setConversationStopPending(cid, false)
      }
    } catch (err) {
      setConversationStopPending(cid, false)
      setError(err.message || '停止响应失败')
    }
  }, [activeId, setConversationStopPending, stopPendingConversations, streamingConversations])

  const handleSubmit = useCallback(async (e) => {
    e.preventDefault()
    if (!input.trim() || (activeId && streamingConversations[activeId])) return
    setError('')
    shouldAutoScrollRef.current = true
    const prompt = input.trim()
    let cid = activeId
    let conv = activeId ? (msgStore[activeId] ?? activeConv) : null
    setInput('')
    try {
      if (!conv) {
        conv = await createConv()
        cid = conv.id
      } else {
        cid = conv.id
      }
      const timestamp = new Date().toISOString()
      const um = { id: `u-${createUuid()}`, role: 'user', content: prompt, timestamp, parts: [{ type: 'text', content: prompt }] }
      const pendingConversation = {
        ...conv,
        model: selModel,
        updated_at: timestamp,
        messages: [...(conv.messages ?? []), um, draftAssistant()],
      }
      setConversationStopPending(cid, false)
      setConversationStreaming(cid, true)
      setMsgStore((s) => ({ ...s, [cid]: pendingConversation }))
      updateSummary(makeConversationSummary(pendingConversation))
      const r = await api(`/api/conversations/${cid}/messages`, {
        method: 'POST',
        body: JSON.stringify({ content: prompt, model: selModel, thinking_enabled: thinkingEnabled }),
      })
      if (!r.ok || !r.body) throw new Error('发送消息失败')
      await readSSE(r, cid)
    } catch (err) {
      setError(err.message)
      if (cid && err.fallback && err.conversation) {
        replaceDraft(cid, err.fallback, err.conversation)
      } else if (cid) {
        clearDraftThinkingTimer(cid)
        const fallback = localError()
        updateDraft(cid, (m) => ({ ...fallback, id: m.id, timestamp: m.timestamp }))
      }
    } finally {
      if (cid) clearDraftThinkingTimer(cid)
      clearConversationStreamState(cid)
      try {
        await refreshAuthState()
      } catch {
        // Ignore auth refresh failures after sending; a later retry will resync the state.
      }
    }
  }, [input, activeId, activeConv, msgStore, selModel, thinkingEnabled, clearConversationStreamState, clearDraftThinkingTimer, createConv, readSSE, refreshAuthState, replaceDraft, setConversationStopPending, setConversationStreaming, streamingConversations, updateDraft, updateSummary])

  const handleFeedback = useCallback(async (mid, fb) => {
    const cid = activeId
    if (!cid || fbPending.includes(mid)) return
    const cv = msgStore[cid]; const tm = cv?.messages.find((m) => m.id === mid)
    if (!tm || !canFeedback(tm)) return
    const prev = tm.feedback ?? null
    const next = prev === fb ? null : fb
    setFbPending((p) => [...p, mid])
    setMsgStore((s) => ({ ...s, [cid]: { ...s[cid], messages: s[cid].messages.map((m) => (m.id === mid ? { ...m, feedback: next } : m)) } }))
    try {
      const r = await api(`/api/conversations/${cid}/feedback`, { method: 'POST', body: JSON.stringify({ message_id: mid, feedback: next }) })
      if (!r.ok) throw new Error()
    } catch {
      setMsgStore((s) => {
        const cv2 = s[cid]; if (!cv2) return s
        return { ...s, [cid]: { ...cv2, messages: cv2.messages.map((m) => (m.id === mid ? { ...m, feedback: prev } : m)) } }
      })
    } finally { setFbPending((p) => p.filter((x) => x !== mid)) }
  }, [activeId, fbPending, msgStore])

  // --- Auth check ---
  if (!authChecked) return <div className="loading-screen"><div className="loading-spinner" /><p>正在加载…</p></div>
  if (!user) return <LoginPage onLogin={handleLogin} />

  // --- Main UI ---
  return (
    <div className={`app-shell ${sidebarCollapsed ? 'app-shell--sidebar-collapsed' : ''}`}>
      {/* Mobile toggle */}
      <button className="sidebar-toggle" onClick={() => setSidebarOpen((v) => !v)} type="button">☰</button>

      <aside className={`sidebar ${sidebarOpen ? 'sidebar--open' : ''} ${sidebarCollapsed ? 'sidebar--collapsed' : ''}`}>
        <div className="sidebar-top">
          <div className="brand-card">
            <img src="/assets/FZU.png" alt="FZU" className="brand-logo" />
            <div>
              <h1>福大灵犀</h1>
              <p className="brand-sub">智能问答 · 教务查询</p>
            </div>
          </div>

          <div className="user-card">
            <div className="user-avatar">{user.display_name?.charAt(0) || 'U'}</div>
            <div className="user-info">
              <strong>{user.display_name}</strong>
              <span>{user.student_type === 'undergraduate' ? '本科生' : '研究生'}
                {user.edu_authenticated ? ' · 教务已连接' : needsEduRelogin ? ' · 教务待重新连接' : ''}</span>
            </div>
            <button className="logout-btn" onClick={handleLogout} type="button" title="退出登录">⏻</button>
          </div>

          {needsEduRelogin ? (
            <EduReloginPanel
              message={eduError}
              studentId={user.user_id}
              onSubmit={handleEduRelogin}
            />
          ) : eduError ? <div className="edu-warn">{eduError}</div> : null}

          <button className="new-chat-btn" onClick={handleNew} type="button">
            <span className="plus-icon">+</span> 新建对话
          </button>
        </div>

        <div className="sidebar-model">
          <label htmlFor="model-sel">模型</label>
          <select id="model-sel" value={selModel} onChange={(e) => setSelModel(e.target.value)}>
            {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
          <div className="thinking-panel">
            <div className="thinking-panel__copy">
              <span className="thinking-panel__title">思考模式</span>
              <span className="thinking-panel__hint">{thinkingEnabled ? '更深入，但响应会更慢' : '直接回复，速度更快'} · 影响下一条消息</span>
            </div>
            <button
              type="button"
              className={`thinking-toggle ${thinkingEnabled ? 'thinking-toggle--on' : ''}`}
              role="switch"
              aria-checked={thinkingEnabled}
              aria-label={thinkingEnabled ? '关闭思考模式' : '开启思考模式'}
              onClick={() => setThinkingEnabled((value) => !value)}
            >
              <span className="thinking-toggle__track">
                <span className="thinking-toggle__thumb" />
              </span>
            </button>
          </div>
        </div>

        <div className="sidebar-convos">
          <div className="section-title">对话历史</div>
          <div className="convo-list">
            {conversations.length === 0
              ? <div className="empty-hint">暂无历史对话</div>
              : conversations.map((c) => (
                <div key={c.id} className={`convo-item ${c.id === activeId ? 'convo-item--active' : ''}`}>
                  <button type="button" className="convo-select" onClick={() => { setActiveId(c.id); setSidebarOpen(false) }}>
                    <div className="convo-item-body">
                      <strong className={`convo-title ${pendingTitles[c.id] ? 'convo-title--pending' : ''}`.trim()} aria-label={pendingTitles[c.id] ? '正在生成标题' : c.title}>
                        {pendingTitles[c.id] ? <PendingTitle compact /> : c.title}
                      </strong>
                      <span>{c.preview || '等待第一条消息…'}</span>
                    </div>
                  </button>
                  <button type="button" className="convo-del" aria-label={`删除${c.title}`} onClick={() => void handleDelete(c.id)}>×</button>
                </div>
              ))
            }
          </div>
        </div>
      </aside>

      <main className="chat-area">
        <header className="chat-header">
          <div className="chat-header-left">
            <button
              type="button"
              className="sidebar-desktop-toggle"
              onClick={toggleDesktopSidebar}
              aria-label={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
              aria-expanded={!sidebarCollapsed}
            >
              {sidebarCollapsed ? '☰' : '⟨'}
            </button>
            <div className="chat-header-copy">
              <h2 className={`chat-header-title ${activeConv && pendingTitles[activeConv.id] ? 'chat-header-title--pending' : ''}`.trim()} aria-label={activeConv && pendingTitles[activeConv.id] ? '正在生成标题' : (activeConv?.title ?? '新的对话')}>
                {activeConv && pendingTitles[activeConv.id] ? <PendingTitle /> : (activeConv?.title ?? '新的对话')}
              </h2>
              <p>福州大学知识库 · 联网搜索 · 教务系统</p>
            </div>
          </div>
          <div className="chat-header-badges">
            <div className="chat-header-badge">{models.find((m) => m.id === selModel)?.label ?? selModel}</div>
            <div className={`chat-header-badge chat-header-badge--thinking ${thinkingEnabled ? 'chat-header-badge--thinking-on' : ''}`}>
              {thinkingEnabled ? '思考开启' : '思考关闭'}
            </div>
          </div>
        </header>

        <section className="msg-list" ref={msgListRef} onScroll={syncAutoScrollState} onWheel={handleMsgListWheel}>
          {activeMsgs.length === 0 ? (
            <div className="empty-state">
              <img src="/assets/FZU.png" alt="logo" className="empty-logo" />
              <h3>开始一次新对话</h3>
              <p>{EMPTY_MSG}</p>
              <div className="quick-actions">
                <button type="button" onClick={() => setInput('查询我的成绩')}>📊 查询成绩</button>
                <button type="button" onClick={() => setInput('查询我的课表')}>📅 查看课表</button>
                <button type="button" onClick={() => setInput('福州大学校训是什么')}>🏫 校训是什么</button>
                <button type="button" onClick={() => setInput('福州大学最新通知')}>📢 最新通知</button>
              </div>
            </div>
          ) : (
            activeMsgs.map((m) => {
              const parts = compactParts(m.parts)
              const citationMap = buildCitationLinkMap(m.id, parts)
              const hasRunningTool = hasRunningToolPart(parts)
              const showBubble = parts.length > 0 || m.isDraft
              const showThinkingIndicator = m.isDraft && !hasRunningTool && (m.showThinkingIndicator ?? parts.length === 0)
              const isDraftWaiting = showThinkingIndicator && parts.length === 0
              const bubbleClassName = [
                'msg-bubble',
                isDraftWaiting ? 'msg-bubble--thinking' : '',
              ].filter(Boolean).join(' ')

              return (
                <article key={m.id} className={`msg-row ${m.role === 'user' ? 'msg-row--user' : ''}`}>
                  <div className={`avatar ${m.role === 'user' ? 'avatar--user' : 'avatar--bot'}`}>
                    {m.role === 'user' ? (user.display_name?.charAt(0) || 'U') : <img src="/assets/FZU.png" alt="bot" />}
                  </div>
                  <div className="msg-body">
                    <div className="msg-meta">
                      <span>{m.role === 'user' ? user.display_name : '福大灵犀'}</span>
                      <time>{fmt(m.timestamp)}</time>
                    </div>
                    {showBubble && (
                      <div className={bubbleClassName}>
                        <div className="msg-bubble-content">
                          {parts.map((p, i) =>
                            p.type === 'tool' ? (
                              <ToolCard
                                key={p.tool_id ?? `${m.id}-tool-${i}`}
                                part={p}
                                conversationId={activeId}
                                messageId={m.id}
                                onMemoryProposalAction={handleMemoryProposalAction}
                              />
                            ) : (
                              <MessageMarkdown key={`${m.id}-text-${i}`} content={p.content} citationMap={citationMap} />
                            ),
                          )}
                          {showThinkingIndicator && (
                            <div className={`thinking-indicator ${isDraftWaiting ? '' : 'thinking-indicator--inline'}`.trim()} role="status" aria-live="polite" aria-label="正在思考">
                              <span className="thinking-indicator__label">正在思考</span>
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                    {canFeedback(m) && (
                      <div className="feedback-row">
                        <button type="button" disabled={fbPending.includes(m.id)} className={m.feedback === 'up' ? 'fb-btn fb-btn--on' : 'fb-btn'} onClick={() => void handleFeedback(m.id, 'up')}>👍</button>
                        <button type="button" disabled={fbPending.includes(m.id)} className={m.feedback === 'down' ? 'fb-btn fb-btn--on' : 'fb-btn'} onClick={() => void handleFeedback(m.id, 'down')}>👎</button>
                      </div>
                    )}
                  </div>
                </article>
              )
            })
          )}
        </section>

        <footer className="composer-area">
          {error && <div className="err-banner">{error}</div>}
          <form className="composer" onSubmit={handleSubmit}>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="输入问题，按 Enter 发送，Shift+Enter 换行"
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void handleSubmit(e) } }}
            />
            <button
              className={`send-btn ${isActiveConversationStreaming ? 'send-btn--stop' : ''}`}
              type={isActiveConversationStreaming ? 'button' : 'submit'}
              disabled={isActiveConversationStreaming ? isActiveConversationStopPending : !input.trim()}
              onClick={isActiveConversationStreaming ? () => { void handleStop() } : undefined}
              aria-label={isActiveConversationStreaming ? '停止响应' : '发送消息'}
              title={isActiveConversationStreaming ? '停止响应' : '发送消息'}
            >
              {isActiveConversationStreaming ? '■' : '➤'}
            </button>
          </form>
        </footer>
      </main>
    </div>
  )
}

export default App
