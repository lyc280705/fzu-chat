import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Check,
  ChevronDown,
  ChevronUp,
  BookOpen,
  Copy,
  Eye,
  EyeOff,
  LogOut,
  MapPin,
  Menu,
  MessageSquarePlus,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  RefreshCw,
  Search,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Utensils,
  X,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ChatComposer } from './components/ChatComposer.jsx'
import { EmptyChatState } from './components/EmptyChatState.jsx'
import { ConfirmDialog, IconButton } from './components/ui.jsx'
import { useAutoResizeTextarea } from './hooks/useAutoResizeTextarea.js'
import { useEscapeKey } from './hooks/useEscapeKey.js'
import './App.css'

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const EMPTY_MSG = '你好呀！我是福大灵犀，你可以向我提问关于福州大学的任何问题，也可以查询你的成绩和课表哦～'
const AUTO_SCROLL_THRESHOLD = 80
const THINKING_INDICATOR_DELAY = 1000
const THINKING_STORAGE_KEY = 'fzu_thinking_enabled'
const SIDEBAR_COLLAPSED_STORAGE_KEY = 'fzu_sidebar_collapsed'
const LOCATION_RECOMMENDATION_STORAGE_KEY = 'fzu_location_recommendations_enabled'
const MESSAGE_MAX_LENGTH = 4000

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
  recommend_campus_context: '📍',
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

const CAMPUS_RECOMMENDATION_SCENARIO_LABELS = {
  auto: '智能校园推荐',
  dining: '食堂推荐',
  study: '自习/复习建议',
}

const CAMPUS_RECOMMENDATION_LOCATION_LABELS = {
  qishan_center: '旗山校区中心区',
  qishan_teaching: '旗山校区教学区',
  qishan_dorm: '旗山校区生活区',
  qishan_library: '旗山校区图书馆',
  qishan_jinjiang: '晋江楼学习中心',
  qishan_staff_center: '教工活动中心 / 桃李园',
  qishan_life_zone_1: '旗山校区生活一区',
  qishan_life_zone_3: '旗山校区生活三区',
  yishan_center: '怡山校区',
  tongpan_center: '铜盘校区',
}

const FALLBACK_HEX = Array.from({ length: 256 }, (_, index) => index.toString(16).padStart(2, '0'))

const PRIVACY_POLICY_SECTIONS = [
  {
    title: '一、适用范围',
    items: [
      '本隐私政策适用于你在使用“福大灵犀”过程中产生的个人信息和相关使用数据处理活动。',
      '本软件的主要功能包括校内知识问答、联网辅助检索、教务系统查询、会话历史保存和个性化长期记忆。',
      '如某项能力处于未开放、灰度测试或临时维护状态，系统会以界面提示或功能限制方式向你说明。',
    ],
  },
  {
    title: '二、我们处理的数据类型',
    items: [
      '账号与认证信息：登录时提交的学号、学生类型，以及为保持登录状态而生成的安全 Cookie。',
      '教务认证信息：你主动输入的教务密码仅用于即时认证与会话续连，前端不会长期保存该密码。',
      '业务内容数据：包括你的提问内容、助手回复、工具调用结果、消息反馈和会话标题。',
      '个性化记忆数据：仅在你明确确认后，系统才会保存长期偏好、常用称呼、输出风格等可复用信息。',
      '本地设备设置：思考模式开关、侧栏折叠状态等界面偏好会保存在当前浏览器本地。',
    ],
  },
  {
    title: '三、数据处理目的',
    items: [
      '用于完成身份识别、教务系统访问控制和持续登录状态维护。',
      '用于生成问答结果、执行课表成绩等教务查询、展示历史记录并维持会话上下文连续性。',
      '用于在你授权或确认的范围内提供个性化回答能力，例如称呼偏好、长期习惯和输出风格偏好。',
      '用于定位系统异常、改善模型效果、控制接口滥用与保障服务稳定运行。',
    ],
  },
  {
    title: '四、敏感信息与最小化原则',
    items: [
      '系统不会将你的教务密码自动写入长期记忆，也不会将密码明文展示在前端页面。',
      '系统默认不建议保存证件号码、手机号、邮箱地址、银行卡号、精确住址等高敏感信息。',
      '如你主动在对话中输入敏感信息，应自行评估风险；除完成当前请求所必需外，系统不会主动扩大使用范围。',
    ],
  },
  {
    title: '五、存储、保留与删除',
    items: [
      '已保存的会话历史、消息反馈和长期记忆会存储在与你当前账号关联的服务端数据文件中。',
      '你可以在侧栏逐条删除历史对话，也可以在“隐私与数据”页面一键清空全部已保存的对话和长期记忆。',
      '一键清空同时会将本地界面偏好恢复默认；删除操作完成后，相关数据通常无法恢复。',
    ],
  },
  {
    title: '六、共享、披露与安全措施',
    items: [
      '为完成模型推理、联网搜索或教务查询，系统可能将必要的请求内容发送至对应的模型服务、检索服务或教务接口。',
      '系统采取基于会话隔离、受限存储文件权限和登录鉴权的方式减少未授权访问风险。',
      '除法律法规要求、主管机关依法要求或为保障系统安全运行所必要外，我们不会无故向无关第三方披露你的数据。',
    ],
  },
  {
    title: '七、你的权利',
    items: [
      '你有权查看本隐私政策、了解系统处理的数据范围，并自主决定是否继续使用本软件。',
      '你有权删除单条历史对话、拒绝记忆建议、取消反馈，以及在数据管理页面执行一键清空。',
      '如你不再同意本隐私政策，可以停止使用本软件，并在退出前删除已保存的数据。',
    ],
  },
]

const USER_AGREEMENT_SECTIONS = [
  {
    title: '一、协议适用与接受',
    items: [
      '本用户协议适用于你对“福大灵犀”全部功能的访问、登录和使用行为。',
      '当你勾选同意并完成登录，即视为你已经阅读、理解并接受本协议及相关隐私政策。',
      '如你不同意本协议任何内容，请不要登录或继续使用本软件。',
    ],
  },
  {
    title: '二、服务内容',
    items: [
      '本软件提供福州大学相关知识问答、联网辅助检索、教务数据查询、历史会话管理和个性化辅助能力。',
      '部分能力依赖第三方模型服务、检索服务或学校教务接口，服务范围可能随实际运行情况调整。',
      '研究生登录、特定工具或实验性能力如未开放，系统可通过界面提示、禁用按钮或其他限制方式说明。',
    ],
  },
  {
    title: '三、账号与认证义务',
    items: [
      '你应确保所提交的身份信息真实、合法，并仅使用你本人有权使用的账号进行登录与查询。',
      '你应妥善保管教务账号及相关凭证，不得借用、出租、转让、出售或冒用他人身份使用本软件。',
      '因你自身保管不善、误操作或主动泄露账号信息造成的风险和损失，应由你自行承担。',
    ],
  },
  {
    title: '四、合理使用规则',
    items: [
      '你不得利用本软件从事违法违规、破坏系统稳定、批量爬取、越权访问、攻击接口或其他滥用行为。',
      '你不得借助模型输出、工具调用或系统缺陷获取、推断或传播其他用户的数据、凭证或隐私信息。',
      '你不得将本软件输出内容伪装为学校官方结论、行政决定或未经核验的正式通知进行传播。',
    ],
  },
  {
    title: '五、结果说明与责任边界',
    items: [
      '本软件输出内容基于模型生成、知识库检索、联网搜索和教务系统返回结果综合生成，仅供辅助参考。',
      '成绩、课表、通知、校历等内容仍应以学校官方系统、公示信息和主管部门说明为准。',
      '因模型误差、数据延迟、接口异常、网络故障、上游服务中断或学校系统维护导致的不准确、不完整或暂时不可用，不构成平台违约。',
    ],
  },
  {
    title: '六、服务变更、中断与终止',
    items: [
      '基于安全、维护、合规或技术升级需要，平台可以对功能范围、接口依赖、访问频率和服务形态进行调整。',
      '如发现异常登录、可疑请求、超出合理范围的频繁访问或其他安全风险，平台可暂停或终止相应服务。',
      '你停止使用本软件或主动清空数据后，系统将不再继续基于已删除内容提供历史连续性服务。',
    ],
  },
  {
    title: '七、协议更新',
    items: [
      '本协议内容可能根据功能变化、合规要求或服务调整进行更新。',
      '更新后的协议将通过登录页或系统内页面向你展示；如更新内容对权利义务有实质影响，平台可要求你重新确认。',
      '你在协议更新后继续登录或使用本软件的，视为你接受更新后的协议内容。',
    ],
  },
]

const LEGAL_DOCUMENTS = {
  privacy: {
    key: 'privacy',
    label: '隐私政策',
    title: '福大灵犀隐私政策',
    intro: '本政策用于说明本软件在账号登录、教务查询、问答会话、个性化记忆和本地设置等场景下的数据处理方式，以及你可行使的管理与删除权利。',
    effectiveDate: '2026-04-24',
    audience: '适用于所有访问、登录或使用本软件的用户',
    sections: PRIVACY_POLICY_SECTIONS,
  },
  terms: {
    key: 'terms',
    label: '用户协议',
    title: '福大灵犀用户协议',
    intro: '本协议用于说明你在登录和使用本软件时应遵守的规则，以及平台服务范围、责任边界和协议更新机制。',
    effectiveDate: '2026-04-24',
    audience: '适用于所有登录并使用本软件功能的用户',
    sections: USER_AGREEMENT_SECTIONS,
  },
}

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

const stoppedAssistant = (message) => ({
  ...message,
  isStopped: true,
  stream_stopped: true,
})

const STOPPED_FALLBACK_TEXT = '已停止响应。'

const stoppedToolPart = (part) => {
  if (part?.type !== 'tool' || part.status !== 'running') return part
  const label = String(part.status_label || part.tool_name || '工具调用')
  return { ...part, status: 'stopped', status_label: `${label}（已停止）` }
}

const mergeStoppedAssistantWithDraft = (message, draft) => {
  const normalizedMessage = stoppedAssistant(message)
  if (!draft?.isDraft) return normalizedMessage

  const draftText = messageTextContent(draft)
  const incomingText = messageTextContent(normalizedMessage)
  const shouldPreserveDraft =
    Boolean(draftText) &&
    (!incomingText || incomingText === STOPPED_FALLBACK_TEXT || incomingText.length < draftText.length)

  if (!shouldPreserveDraft) return normalizedMessage

  const draftParts = compactParts(
    draft.parts?.length ? draft.parts.map(stoppedToolPart) : [{ type: 'text', content: draftText }],
  )
  return {
    ...normalizedMessage,
    content: draft.content || draftText,
    parts: draftParts,
    reasoning_content: normalizedMessage.reasoning_content ?? draft.reasoning_content,
  }
}

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

const messageTextContent = (message) =>
  compactParts(message?.parts?.length ? message.parts : message?.content ? [{ type: 'text', content: message.content }] : [])
    .filter((part) => part.type === 'text')
    .map((part) => part.content)
    .join('\n')
    .trim()

const copyTextToClipboard = async (text) => {
  if (!text) return false
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Fall through to the textarea fallback for browsers with stricter clipboard gates.
    }
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.inset = '0 auto auto 0'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  textarea.setSelectionRange(0, text.length)
  try {
    return document.execCommand('copy')
  } finally {
    document.body.removeChild(textarea)
  }
}

const userTextParts = (content) => [{ type: 'text', content }]

const previousUserMessage = (messages = [], messageId) => {
  const startIndex = messages.findIndex((message) => message.id === messageId)
  if (startIndex < 0) return null
  for (let index = startIndex - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === 'user') return messages[index]
  }
  return null
}

const canFeedback = (m) => m.role === 'assistant' && !m.isDraft && !m.isLocalOnly && !m.isErrorFallback
const isStoppedMessage = (m) => Boolean(m?.isStopped ?? m?.is_stopped ?? m?.stream_stopped)

const STATUS_LABELS = {
  pending_confirmation: '等待确认',
  saved: '已保存',
  deleted: '已删除',
  dismissed: '已忽略',
  already_saved: '已存在',
  already_deleted: '已删除',
  not_found: '未找到',
  invalid: '无效',
  unavailable: '不可用',
  error: '失败',
  success: '已成功',
  submitted: '已提交',
  open: '开放中',
  closed: '未开放',
  upcoming: '未开始',
  unknown: '状态未知',
}

const statusLabel = (status, fallback = '状态未知') => {
  const value = String(status || '').trim()
  if (!value) return fallback
  if (STATUS_LABELS[value]) return STATUS_LABELS[value]
  return /[\u4e00-\u9fff]/.test(value) ? value : fallback
}

const parseJsonObject = (value) => {
  if (!value || typeof value !== 'string') return null
  const trimmed = value.trim()
  if (!trimmed.startsWith('{') || !trimmed.endsWith('}')) return null
  try {
    const parsed = JSON.parse(trimmed)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null
  } catch {
    return null
  }
}

const normalizeCampusRecommendationData = (data) => {
  if (data && typeof data === 'object' && !Array.isArray(data)) return data
  const parsed = parseJsonObject(data)
  return parsed && Array.isArray(parsed.recommendations) ? parsed : null
}

const campusRecommendationArgsSummary = (value, data = null) => {
  const args = typeof value === 'string' ? parseJsonObject(value) : value
  if (args && typeof args === 'object' && !Array.isArray(args)) {
    const scenario = String(args.scenario || data?.scenario || data?.resolved_scenario || 'auto').trim()
    const parts = [`场景：${CAMPUS_RECOMMENDATION_SCENARIO_LABELS[scenario] || '智能校园推荐'}`]
    const manualLocation = String(args.manual_location_id || '').trim()
    if (manualLocation && CAMPUS_RECOMMENDATION_LOCATION_LABELS[manualLocation]) {
      parts.push(`位置：${CAMPUS_RECOMMENDATION_LOCATION_LABELS[manualLocation]}`)
    } else if (args.latitude && args.longitude) {
      parts.push('位置：本次授权定位')
    } else if (data?.location_name) {
      parts.push(`位置：${data.location_name}`)
    } else {
      parts.push('位置：按校内地点库估算')
    }
    return parts.join('；')
  }
  if (data?.title || data?.location_name) {
    return [data.title, data.location_name ? `位置：${data.location_name}` : ''].filter(Boolean).join('；')
  }
  return ''
}

const toolQueryText = (part = {}) => {
  if (part.tool_name === 'recommend_campus_context') {
    const data = normalizeCampusRecommendationData(part.data)
    const summary = campusRecommendationArgsSummary(part.query, data)
    if (summary) return summary
    const raw = String(part.query || '').trim()
    return raw.startsWith('{') ? '' : raw
  }
  return String(part.query || '').trim()
}

const toolResultSummary = (part = {}) => {
  const data = part.data
  if (!data) return ''
  if (part.tool_name === 'retrieve' || part.tool_name === 'bocha_websearch_tool') {
    const count = Array.isArray(data.items) ? data.items.length : 0
    return count ? `${count} 条来源` : ''
  }
  if (part.tool_name === 'query_grades' && Array.isArray(data)) return `${data.length} 门课程`
  if (part.tool_name === 'query_courses' && Array.isArray(data)) return `${data.length} 节课程`
  if (part.tool_name === 'query_exam_scores' && Array.isArray(data)) return `${data.length} 条成绩`
  if (part.tool_name === 'query_exam_rooms' && Array.isArray(data.exams)) return `${data.exams.length} 场考试`
  if (part.tool_name === 'query_user_memory' && Array.isArray(data.memories)) return `${data.memories.length} 条记忆`
  if (part.tool_name === 'recommend_campus_context') {
    const recommendationData = normalizeCampusRecommendationData(data)
    if (Array.isArray(recommendationData?.recommendations)) return `${recommendationData.recommendations.length} 个地点`
  }
  if (data.status) return statusLabel(data.status)
  return ''
}

const memoryToolTitle = (part = {}) => {
  const status = part.data?.status
  if (part.tool_name === 'save_user_memory') {
    return {
      pending_confirmation: '记忆保存待确认',
      saved: '记忆已保存',
      dismissed: '已忽略保存建议',
      already_saved: '记忆已存在',
      invalid: '记忆建议无效',
      unavailable: '暂时无法保存记忆',
      error: '记忆保存失败',
    }[status] || '记忆建议已生成'
  }
  if (part.tool_name === 'delete_user_memory') {
    return {
      pending_confirmation: '记忆删除待确认',
      deleted: '记忆已删除',
      dismissed: '已忽略删除建议',
      already_deleted: '记忆已不存在',
      not_found: '未找到待删除记忆',
      invalid: '删除建议无效',
      unavailable: '暂时无法删除记忆',
      error: '记忆删除失败',
    }[status] || '记忆删除建议已生成'
  }
  return ''
}

const toolCardTitle = (part = {}) => {
  const memoryTitle = memoryToolTitle(part)
  if (memoryTitle) return memoryTitle
  return part.status_label || '工具调用'
}

const normMsgs = (msgs = []) =>
  msgs.map((m) => ({
    ...m,
    isErrorFallback: m.isErrorFallback ?? m.is_error_fallback ?? false,
    isLocalOnly: m.isLocalOnly ?? false,
    isStopped: isStoppedMessage(m),
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

const readApiError = async (response, fallback = '请求失败', rateLimitMessage = '') => {
  const payload = await response.json().catch(() => ({}))
  if (response.status === 429 && rateLimitMessage) return rateLimitMessage
  return payload?.detail || payload?.message || fallback
}

const isLocalhostForGeolocation = (hostname = '') => (
  hostname === 'localhost'
  || hostname === '127.0.0.1'
  || hostname === '[::1]'
  || hostname === '::1'
)

const isSecureGeolocationContext = () => {
  if (globalThis.isSecureContext === true) return true
  const location = globalThis.location
  if (!location) return false
  return location.protocol === 'https:' || isLocalhostForGeolocation(location.hostname)
}

const geolocationErrorMessage = (error) => {
  if (!error) return '无法获取浏览器定位。'
  if (error.code === 1) return '定位权限被拒绝，你可以手动选择所在校区或区域。'
  if (error.code === 2) return '暂时无法获取当前位置，你可以手动选择所在校区或区域。'
  if (error.code === 3) return '定位请求超时，你可以手动选择所在校区或区域。'
  return error.message || '无法获取浏览器定位。'
}

const refineGeolocationErrorMessage = (message, permissionState) => {
  const fallback = message || '无法获取浏览器定位，你可以手动选择所在校区或区域。'
  if (permissionState === 'insecure') return '当前访问地址不是 HTTPS 安全页面，手机浏览器不会弹出定位授权。请使用 HTTPS 域名访问，或仅在 localhost 开发环境测试。'
  if (permissionState === 'denied') return '当前站点定位权限已被浏览器拒绝，请在浏览器站点设置中改为允许，或继续使用手动位置。'
  if (permissionState === 'prompt' && /拒绝|denied/i.test(fallback)) {
    return '浏览器没有弹出定位授权窗口，可能被系统定位服务、浏览器站点设置或内嵌浏览器策略拦截。请在系统/浏览器中允许定位，或继续使用手动位置。'
  }
  return fallback
}

const requestBrowserLocation = ({ timeout = 8000, maximumAge = 60000 } = {}) => new Promise((resolve, reject) => {
  const nav = globalThis.navigator
  if (!isSecureGeolocationContext()) {
    reject(new Error('当前访问地址不是 HTTPS 安全页面，手机浏览器不会弹出定位授权。请使用 HTTPS 域名访问，或仅在 localhost 开发环境测试。'))
    return
  }
  if (!nav?.geolocation) {
    reject(new Error('当前浏览器不支持定位，你可以手动选择所在校区或区域。'))
    return
  }
  nav.geolocation.getCurrentPosition(
    (position) => resolve({
      lat: position.coords.latitude,
      lng: position.coords.longitude,
      accuracy: position.coords.accuracy,
    }),
    (error) => reject(new Error(geolocationErrorMessage(error))),
    { enableHighAccuracy: false, timeout, maximumAge },
  )
})

const queryGeolocationPermission = async () => {
  const nav = globalThis.navigator
  if (!isSecureGeolocationContext()) return 'insecure'
  if (!nav?.geolocation) return 'unsupported'
  if (!nav.permissions?.query) return 'unknown'
  try {
    const status = await nav.permissions.query({ name: 'geolocation' })
    return status.state || 'unknown'
  } catch {
    return 'unknown'
  }
}

const locationPermissionLabel = (state) => ({
  granted: '已允许',
  prompt: '待授权',
  denied: '已被浏览器拒绝',
  insecure: '非 HTTPS，无法弹窗',
  unsupported: '当前浏览器不支持',
  unknown: '状态未知',
}[state] || '状态未知')

const formatDistanceMeters = (value) => {
  const meters = Number(value)
  if (!Number.isFinite(meters)) return '距离未知'
  if (meters >= 1000) return `${(meters / 1000).toFixed(meters >= 2000 ? 0 : 1)} 公里`
  return `${Math.max(1, Math.round(meters))} 米`
}

/* ================================================================== */
/*  Login Page                                                         */
/* ================================================================== */

function LegalDocumentSections({ document }) {
  return (
    <article className="privacy-card">
      <span className="privacy-eyebrow">{document.label}</span>
      <h3>{document.title}</h3>
      <p>{document.intro}</p>
      <div className="privacy-doc-meta">
        <span>生效日期：{document.effectiveDate}</span>
        <span>适用对象：{document.audience}</span>
      </div>
      <div className="privacy-doc-sections">
        {document.sections.map((section) => (
          <section key={section.title} className="privacy-subsection">
            <h4>{section.title}</h4>
            <ul className="privacy-policy-list">
              {section.items.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </section>
        ))}
      </div>
    </article>
  )
}

function LegalDocumentPage({ documentKey, onBack }) {
  const document = LEGAL_DOCUMENTS[documentKey] ?? LEGAL_DOCUMENTS.privacy

  return (
    <div className="login-page login-page--legal">
      <div className="legal-page">
        <div className="legal-page__toolbar">
          <button type="button" className="secondary-btn legal-page__back" onClick={onBack}>返回登录</button>
        </div>
        <LegalDocumentSections document={document} />
      </div>
    </div>
  )
}

function LoginPage({ onLogin }) {
  const [studentId, setStudentId] = useState('')
  const [password, setPassword] = useState('')
  const [studentType, setStudentType] = useState('undergraduate')
  const [acceptedLegal, setAcceptedLegal] = useState(false)
  const [legalDocumentKey, setLegalDocumentKey] = useState(null)
  const [passwordVisible, setPasswordVisible] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [logoFailed, setLogoFailed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const studentIdRef = useRef(null)
  const passwordRef = useRef(null)

  const studentIdError = submitted && !studentId.trim() ? '请输入学号。' : ''
  const passwordError = submitted && !password.trim() ? '请输入教务系统密码。' : ''
  const legalError = submitted && !acceptedLegal ? '请先阅读并同意协议。' : ''

  if (legalDocumentKey) {
    return <LegalDocumentPage documentKey={legalDocumentKey} onBack={() => setLegalDocumentKey(null)} />
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitted(true)
    if (!studentId.trim()) {
      studentIdRef.current?.focus()
      return
    }
    if (!password.trim()) {
      passwordRef.current?.focus()
      return
    }
    if (!acceptedLegal) {
      setError('请先阅读并勾选同意《用户协议》和《隐私政策》。')
      return
    }
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ student_id: studentId.trim(), password: password.trim(), student_type: studentType, accepted_legal: true }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || '登录失败')
      }
      const data = await res.json()
      onLogin(data.user, data.edu_error || '')
    } catch (err) {
      setError(err.message)
      studentIdRef.current?.focus()
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          {logoFailed ? (
            <div className="login-logo login-logo--fallback" aria-hidden="true">F</div>
          ) : (
            <img src="/assets/FZU.png" alt="福州大学" className="login-logo" onError={() => setLogoFailed(true)} />
          )}
          <h1>福大灵犀</h1>
          <p>福州大学智能问答助手</p>
        </div>
        <form className="login-form" onSubmit={handleSubmit}>
          {error && <div className="login-error" role="alert">{error}</div>}
          <label className={studentIdError ? 'field field--error' : 'field'}>
            <span>学号</span>
            <input
              ref={studentIdRef}
              type="text"
              value={studentId}
              onChange={(e) => {
                setStudentId(e.target.value)
                if (error) setError('')
              }}
              placeholder="请输入学号"
              autoComplete="username"
              aria-invalid={Boolean(studentIdError)}
              aria-describedby={studentIdError ? 'login-student-id-error' : undefined}
              autoFocus
            />
            {studentIdError && <span id="login-student-id-error" className="field-error">{studentIdError}</span>}
          </label>
          <label className={passwordError ? 'field field--error' : 'field'}>
            <span>密码</span>
            <div className="password-field">
              <input
                ref={passwordRef}
                type={passwordVisible ? 'text' : 'password'}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value)
                  if (error) setError('')
                }}
                placeholder="教务系统密码"
                autoComplete="current-password"
                aria-invalid={Boolean(passwordError)}
                aria-describedby={passwordError ? 'login-password-error' : undefined}
              />
              <IconButton
                label={passwordVisible ? '隐藏密码' : '显示密码'}
                className="password-toggle"
                onClick={() => setPasswordVisible((value) => !value)}
              >
                {passwordVisible ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
              </IconButton>
            </div>
            {passwordError && <span id="login-password-error" className="field-error">{passwordError}</span>}
          </label>
          <label>
            <span>学生类型</span>
            <select value={studentType} onChange={(e) => setStudentType(e.target.value)}>
              <option value="undergraduate">本科生</option>
              <option value="graduate" disabled>研究生（暂未开放）</option>
            </select>
            <span className="field-hint">研究生登录入口暂未开放，当前仅支持本科教务认证。</span>
          </label>

          <div className={legalError ? 'login-consent login-consent--error' : 'login-consent'}>
            <input
              id="login-legal-consent"
              className="login-consent__input"
              type="checkbox"
              checked={acceptedLegal}
              onChange={(event) => {
                setAcceptedLegal(event.target.checked)
                if (event.target.checked) setError('')
              }}
            />
            <label htmlFor="login-legal-consent" className="login-consent__prefix">我已阅读并同意</label>
            <button type="button" className="login-link-btn" onClick={() => setLegalDocumentKey('terms')}>《用户协议》</button>
            <span className="login-consent__sep">和</span>
            <button type="button" className="login-link-btn" onClick={() => setLegalDocumentKey('privacy')}>《隐私政策》</button>
          </div>
          {legalError && <span className="field-error field-error--standalone">{legalError}</span>}

          <button type="submit" className="login-btn" disabled={loading}>
            {loading ? '登录中…' : '登 录'}
          </button>
        </form>
        <p className="login-footer">密码仅用于即时教务认证，登录态通过站点安全 Cookie 保存；登录前请先阅读并同意相关协议。</p>
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
                    <td data-label="课程">{r.name}</td>
                    <td data-label="学分">{r.credits}</td>
                    <td data-label="成绩">{r.score}</td>
                    <td data-label="绩点">{r.gpa}</td>
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
              <td data-label="课程">{r.name}</td>
              <td data-label="教师">{r.teacher}</td>
              <td data-label="学分">{r.credits}</td>
              <td data-label="时间">{r.time}</td>
              <td data-label="地点">{r.location}</td>
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
            <tr key={i}>
              <td data-label="考试">{r.exam_name}</td>
              <td data-label="成绩">{r.score}</td>
              <td data-label="日期">{r.date}</td>
            </tr>
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
              {row.map((cell, cellIndex) => <td key={`${rowIndex}-${cellIndex}`} data-label={headers[cellIndex]}>{cell || '—'}</td>)}
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
  const label = status === 'pending_confirmation' ? '待确认' : statusLabel(status, '不可用')

  return <span className={`memory-status-badge memory-status-badge--${status || 'unavailable'}`}>{label}</span>
}

function UserMemoryListCard({ data }) {
  if (!data || typeof data !== 'object') return null
  const items = Array.isArray(data.items) ? data.items : []
  const hasFilter = Boolean(data.query || data.category)
  const showScore = items.some((item) => item.score !== undefined && item.score !== null)
  const headers = showScore
    ? ['分类', '内容', '备注', '重要度', '匹配分', '更新时间']
    : ['分类', '内容', '备注', '重要度', '更新时间']

  return (
    <div className="tool-sections">
      <div className="tool-summary">
        {hasFilter
          ? `已检索到 ${items.length} 条匹配的个性化记忆`
          : `最近个性化记忆 ${items.length} 条`}
      </div>
      {items.length > 0 ? (
        <StructuredTable
          headers={headers}
          rows={items.map((item) => {
            const base = [item.category || '未分类', item.content || '—', item.reason || '—', item.importance ? `${item.importance}/100` : '—']
            if (showScore) base.push(item.score !== undefined && item.score !== null ? String(item.score) : '—')
            base.push(fmt(item.updated_at) || '—')
            return base
          })}
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
      重要度: data?.importance ? `${data.importance}/100` : '',
      相似度: data?.duplicate_similarity ? `${Math.round(Number(data.duplicate_similarity) * 100)}%` : '',
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
        {status === 'already_saved' && <div className="memory-proposal-note">相同或相似内容已存在，无需重复保存。</div>}
        {status === 'invalid' && <div className="memory-proposal-note">{data?.validation || '这条内容不适合保存为长期个性化记忆。'}</div>}
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
            headers={['分类', '内容', '备注', '重要度', '更新时间']}
            rows={items.map((item) => [item.category || '未分类', item.content || '—', item.reason || '—', item.importance ? `${item.importance}/100` : '—', fmt(item.updated_at) || '—'])}
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

function ContextualRecommendationCard({ data }) {
  if (!data || typeof data !== 'object') return null
  const recommendations = Array.isArray(data.recommendations) ? data.recommendations : []
  const exams = Array.isArray(data.academic_context?.upcoming_exams) ? data.academic_context.upcoming_exams : []
  const signals = Array.isArray(data.academic_context?.signals) ? data.academic_context.signals : []
  const recentClass = data.academic_context?.recent_class
  const nextClass = data.academic_context?.next_class
  const isDining = data.resolved_scenario === 'dining'
  const locationSource = {
    browser: '浏览器定位',
    manual: '手动位置',
    default: '默认估算',
  }[data.location_source] || '位置估算'

  return (
    <section className="campus-recommendation-card" aria-label={data.title || '校园推荐'}>
      <div className="campus-recommendation-card__header">
        <span className="campus-recommendation-card__icon" aria-hidden="true">
          {isDining ? <Utensils size={18} /> : <BookOpen size={18} />}
        </span>
        <div>
          <h4>{data.title || '校园推荐'}</h4>
          {data.trigger_reason && <p>{data.trigger_reason}</p>}
        </div>
      </div>

      <div className="campus-recommendation-meta" aria-label="推荐依据">
        {data.location_name && (
          <span>
            <MapPin size={14} aria-hidden="true" />
            {data.location_name}
          </span>
        )}
        <span>{locationSource}</span>
        <span>{data.map_status === 'amap' ? '高德步行路线' : '校内地点库估算'}</span>
      </div>

      {(signals.length > 0 || recentClass || nextClass || exams.length > 0) && (
        <div className="campus-recommendation-context">
          {signals.slice(0, 3).map((signal) => (
            <span key={`${signal.type}-${signal.title}`}>{signal.title}</span>
          ))}
          {recentClass && <span>刚结束：{recentClass.name}{recentClass.location ? ` · ${recentClass.location}` : ''}</span>}
          {nextClass && <span>下一节：{nextClass.name}{nextClass.location ? ` · ${nextClass.location}` : ''}</span>}
          {exams.slice(0, 2).map((exam) => (
            <span key={`${exam.course_name}-${exam.date}-${exam.time}`}>考试：{exam.course_name || '未命名课程'} · {exam.days_until === 0 ? '今天' : `${exam.days_until} 天后`}</span>
          ))}
        </div>
      )}

      {data.map_note && <div className="campus-recommendation-note">{data.map_note}</div>}

      <div className="campus-recommendation-list">
        {recommendations.length === 0 ? (
          <div className="campus-recommendation-empty">暂时没有可展示的推荐地点。</div>
        ) : recommendations.map((item, index) => (
          <article key={item.id || item.name} className="campus-recommendation-item">
            <div className="campus-recommendation-item__rank">{index + 1}</div>
            <div className="campus-recommendation-item__body">
              <div className="campus-recommendation-item__title">
                <strong>{item.name}</strong>
                {item.campus && <span>{item.campus}</span>}
              </div>
              <div className="campus-recommendation-item__stats">
                <span>步行约 {item.walk_minutes || '—'} 分钟</span>
                <span>{formatDistanceMeters(item.walk_distance_m ?? item.distance_m)}</span>
                <span>{item.route_source === 'amap' ? '高德路线' : '估算'}</span>
              </div>
              {item.reason && <p>{item.reason}</p>}
              {Array.isArray(item.tags) && item.tags.length > 0 && (
                <div className="campus-recommendation-tags">
                  {item.tags.slice(0, 4).map((tag) => <span key={tag}>{tag}</span>)}
                </div>
              )}
            </div>
          </article>
        ))}
      </div>

      {data.privacy_note && <div className="campus-recommendation-privacy">{data.privacy_note}</div>}
    </section>
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
  const isStopped = part.status === 'stopped'
  const needsConfirmation = part.data?.status === 'pending_confirmation'
  const isFailed = part.status === 'error' || ['invalid', 'unavailable', 'error'].includes(part.data?.status)
  const statusClass = isRunning ? 'running' : isStopped ? 'stopped' : isFailed ? 'error' : needsConfirmation ? 'action' : 'done'
  const title = toolCardTitle(part)
  const summary = toolResultSummary(part)
  const showRawUrls = !['query_cultivate_plan', 'retrieve', 'bocha_websearch_tool'].includes(part.tool_name)
  const [expanded, setExpanded] = useState(() => !EDUCATIONAL_TOOL_NAMES.has(part.tool_name))
  const displayQuery = toolQueryText(part)
  const recommendationData = part.tool_name === 'recommend_campus_context'
    ? normalizeCampusRecommendationData(part.data)
    : null

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
      case 'recommend_campus_context':
        return <ContextualRecommendationCard data={recommendationData} />
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
    <div className={`tool-card tool-card--${statusClass}`}>
      <div className="tool-card-header">
        <div className="tool-card-heading">
          <span className="tool-card-icon">{icon}</span>
          <span className="tool-card-title">{title}</span>
          {summary && <span className="tool-card-summary">{summary}</span>}
        </div>
        <div className="tool-card-actions">
          <button
            type="button"
            className="tool-card-toggle"
            onClick={() => setExpanded((value) => !value)}
            aria-expanded={expanded}
            aria-label={expanded ? '收起工具结果' : '展开工具结果'}
          >
            {expanded ? <ChevronUp size={15} aria-hidden="true" /> : <ChevronDown size={15} aria-hidden="true" />}
            <span>{expanded ? '收起' : '展开'}</span>
          </button>
          {isRunning && <span className="tool-spinner" />}
        </div>
      </div>
      {expanded && (
        <div className="tool-card-body">
          {displayQuery && <div className="tool-card-query">{displayQuery}</div>}
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

function PrivacyPolicyView({
  summary,
  loading,
  clearing,
  resetDisabled,
  locationEnabled,
  locationPermission,
  locationBusy,
  locationMessage,
  onReload,
  onReset,
  onEnableLocation,
  onDisableLocation,
  onRefreshLocationPermission,
  error,
}) {
  const stats = [
    { label: '历史对话', value: summary?.conversation_count ?? 0, hint: '包含侧栏中的全部已保存会话' },
    { label: '消息总数', value: summary?.message_count ?? 0, hint: '包括你的提问与助手回复' },
    { label: '长期记忆', value: summary?.memory_count ?? 0, hint: '仅统计已确认保存的个性化记忆' },
  ]

  return (
    <section className="privacy-page">
      <div className="privacy-shell">
        {error && <div className="err-banner">{error}</div>}

        <div className="privacy-hero privacy-card">
          <div className="privacy-hero__copy">
            <span className="privacy-eyebrow">隐私、协议与数据</span>
            <h3>查看使用规则，并管理你已保存的数据</h3>
            <p>这里集中展示隐私政策、用户协议、当前账号数据统计，以及一键清空入口。</p>
          </div>
          <div className="privacy-card__actions">
            <button type="button" className="secondary-btn" onClick={onReload} disabled={loading || clearing}>
              <RefreshCw size={16} aria-hidden="true" /> {loading ? '刷新中…' : '刷新统计'}
            </button>
          </div>
        </div>

        <div className="privacy-stats">
          {stats.map((item) => (
            <article key={item.label} className="privacy-stat privacy-card">
              <span className="privacy-stat__label">{item.label}</span>
              <strong className="privacy-stat__value">{loading ? '…' : item.value}</strong>
              <p className="privacy-stat__hint">{item.hint}</p>
            </article>
          ))}
        </div>

        <div className="privacy-card privacy-card--location">
          <div>
            <h3>定位与智能提醒</h3>
            <p>开启后，灵犀只会在你发送新对话时临时读取一次浏览器定位，用来判断是否适合在回复末尾轻声提醒附近食堂或自习地点。手机访问需要 HTTPS 域名才会弹出定位授权；经纬度不写入会话、长期记忆或服务端日志。</p>
            <div className="privacy-location-status">
              <span>应用开关：{locationEnabled ? '已开启' : '未开启'}</span>
              <span>浏览器权限：{locationPermissionLabel(locationPermission)}</span>
            </div>
            {locationMessage && <div className="privacy-location-message">{locationMessage}</div>}
          </div>
          <div className="privacy-card__actions">
            {locationEnabled ? (
              <button type="button" className="secondary-btn" onClick={onDisableLocation} disabled={locationBusy}>
                关闭定位提醒
              </button>
            ) : (
              <button type="button" className="primary-btn" onClick={onEnableLocation} disabled={locationBusy || locationPermission === 'unsupported'}>
                <MapPin size={16} aria-hidden="true" /> {locationBusy ? '请求中…' : '允许定位提醒'}
              </button>
            )}
            <button type="button" className="secondary-btn" onClick={onRefreshLocationPermission} disabled={locationBusy}>
              <RefreshCw size={16} aria-hidden="true" /> 刷新权限状态
            </button>
          </div>
        </div>

        <div className="privacy-card privacy-card--danger">
          <div>
            <h3>数据管理</h3>
            <p>一键清空会删除服务器上已保存的会话历史、消息反馈、长期记忆，并把当前浏览器里的界面设置恢复为默认值。此操作不可撤销。</p>
          </div>
          <div className="privacy-card__actions">
            <button type="button" className="danger-btn" onClick={onReset} disabled={resetDisabled}>
              {clearing ? '清空中…' : '一键清空已保存数据'}
            </button>
          </div>
        </div>

        {Object.values(LEGAL_DOCUMENTS).map((document) => <LegalDocumentSections key={document.key} document={document} />)}
      </div>
    </section>
  )
}

/* ================================================================== */
/*  Main App                                                           */
/* ================================================================== */

function App() {
  const [user, setUser] = useState(null)
  const [eduError, setEduError] = useState('')
  const [authChecked, setAuthChecked] = useState(false)
  const [viewMode, setViewMode] = useState('chat')

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
  const [userDataSummary, setUserDataSummary] = useState(null)
  const [userDataLoading, setUserDataLoading] = useState(false)
  const [userDataClearing, setUserDataClearing] = useState(false)
  const [error, setError] = useState('')
  const [fbPending, setFbPending] = useState([])
  const [conversationQuery, setConversationQuery] = useState('')
  const [renamingId, setRenamingId] = useState(null)
  const [renamingTitle, setRenamingTitle] = useState('')
  const [renamePending, setRenamePending] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [resetDialogOpen, setResetDialogOpen] = useState(false)
  const [copiedMessageId, setCopiedMessageId] = useState(null)
  const [failedPrompt, setFailedPrompt] = useState(null)
  const [editingMessage, setEditingMessage] = useState(null)
  const [locationRecommendationEnabled, setLocationRecommendationEnabled] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.localStorage.getItem(LOCATION_RECOMMENDATION_STORAGE_KEY) === '1'
  })
  const [locationPermission, setLocationPermission] = useState('unknown')
  const [locationPermissionBusy, setLocationPermissionBusy] = useState(false)
  const [locationPermissionMessage, setLocationPermissionMessage] = useState('')
  const [screenReaderStatus, setScreenReaderStatus] = useState('')
  const [showScrollBottom, setShowScrollBottom] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === '1'
  })
  const msgListRef = useRef(null)
  const composerRef = useRef(null)
  const shouldAutoScrollRef = useRef(true)
  const draftThinkingTimersRef = useRef(new Map())
  const conversationEventsRef = useRef(null)
  const copiedMessageTimerRef = useRef(null)

  const activeConv = useMemo(() => conversations.find((c) => c.id === activeId) ?? null, [activeId, conversations])
  const activeMsgs = useMemo(() => normMsgs(msgStore[activeId]?.messages ?? []), [activeId, msgStore])
  const activeConversationModel = useMemo(
    () => (activeId ? (msgStore[activeId]?.model ?? activeConv?.model ?? '') : ''),
    [activeConv, activeId, msgStore],
  )
  const filteredConversations = useMemo(() => {
    const query = conversationQuery.trim().toLowerCase()
    if (!query) return conversations
    return conversations.filter((conversation) => (
      `${conversation.title ?? ''} ${conversation.preview ?? ''}`.toLowerCase().includes(query)
    ))
  }, [conversationQuery, conversations])
  const userId = user?.user_id ?? ''
  const needsEduRelogin = user?.student_type === 'undergraduate' && !user?.edu_authenticated
  const isActiveConversationStreaming = Boolean(activeId && streamingConversations[activeId])
  const isActiveConversationStopPending = Boolean(activeId && stopPendingConversations[activeId])
  const hasStreamingConversation = Object.keys(streamingConversations).length > 0
  const isPrivacyView = viewMode === 'privacy'
  const inputLength = input.length
  const inputNearLimit = inputLength >= MESSAGE_MAX_LENGTH * 0.9
  const composerStatusText = ''

  useAutoResizeTextarea(composerRef, input)
  useEscapeKey(sidebarOpen, () => setSidebarOpen(false))
  useEscapeKey(Boolean(deleteTarget) && !renamePending, () => setDeleteTarget(null))
  useEscapeKey(resetDialogOpen && !userDataClearing, () => setResetDialogOpen(false))

  const syncAutoScrollState = useCallback(() => {
    const list = msgListRef.current
    if (!list) return true
    const distanceToBottom = list.scrollHeight - list.scrollTop - list.clientHeight
    const shouldAutoScroll = distanceToBottom <= AUTO_SCROLL_THRESHOLD
    shouldAutoScrollRef.current = shouldAutoScroll
    setShowScrollBottom(!shouldAutoScroll)
    return shouldAutoScroll
  }, [])

  const scrollMessagesToBottom = useCallback(() => {
    const list = msgListRef.current
    if (!list) return
    list.scrollTop = list.scrollHeight
    shouldAutoScrollRef.current = true
    setShowScrollBottom(false)
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
    setViewMode('chat')
    setConversations([])
    setMsgStore({})
    setActiveId(null)
    setStreamingConversations({})
    setStopPendingConversations({})
    setPendingTitles({})
    setUserDataSummary(null)
    setUserDataLoading(false)
    setUserDataClearing(false)
    setError('')
    setConversationQuery('')
    setRenamingId(null)
    setRenamingTitle('')
    setRenamePending(false)
    setDeleteTarget(null)
    setResetDialogOpen(false)
    setCopiedMessageId(null)
    setFailedPrompt(null)
    setEditingMessage(null)
    setScreenReaderStatus('')
    setShowScrollBottom(false)
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
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, sidebarCollapsed ? '1' : '0')
  }, [sidebarCollapsed])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(THINKING_STORAGE_KEY, thinkingEnabled ? '1' : '0')
  }, [thinkingEnabled])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(LOCATION_RECOMMENDATION_STORAGE_KEY, locationRecommendationEnabled ? '1' : '0')
  }, [locationRecommendationEnabled])

  useEffect(() => {
    let cancelled = false
    queryGeolocationPermission().then((state) => {
      if (!cancelled) setLocationPermission(state)
    })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!shouldAutoScrollRef.current) return
    scrollMessagesToBottom()
  }, [activeMsgs, scrollMessagesToBottom])

  useEffect(() => {
    shouldAutoScrollRef.current = true
    setShowScrollBottom(false)
    setEditingMessage(null)
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
    if (copiedMessageTimerRef.current) {
      clearTimeout(copiedMessageTimerRef.current)
      copiedMessageTimerRef.current = null
    }
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

  const loadUserDataSummary = useCallback(async () => {
    setUserDataLoading(true)
    try {
      const response = await api('/api/user-data')
      if (response.status === 401) {
        resetAuthState()
        return
      }
      if (!response.ok) throw new Error('加载数据统计失败')
      const payload = await response.json()
      setUserDataSummary(payload)
    } catch (err) {
      setError(err.message || '加载数据统计失败')
    } finally {
      setUserDataLoading(false)
    }
  }, [resetAuthState])

  useEffect(() => {
    if (!userId || viewMode !== 'privacy') return
    void loadUserDataSummary()
  }, [loadUserDataSummary, userId, viewMode])

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
    if (activeConversationModel && models.some((model) => model.id === activeConversationModel)) {
      setSelModel(activeConversationModel)
      return
    }
    if (models.length > 0) {
      setSelModel(models[0].id)
    }
  }, [activeConversationModel, activeId, models])

  // --- Handlers ---
  const handleLogin = useCallback((u, eduErr) => {
    setUser(u)
    setEduError(eduErr)
    setError('')
  }, [])

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
      setViewMode('chat')
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
      setViewMode('chat')
      setActiveId(reusableConversation.id)
      return reusableConversation
    }

    const r = await api('/api/conversations', { method: 'POST', body: JSON.stringify({ model: selModel }) })
    if (!r.ok) throw new Error(await readApiError(r, '创建对话失败', '创建对话过快，请稍后再试。'))
    const c = await r.json()
    setConversations((p) => [makeConversationSummary(c), ...p.filter((item) => item.id !== c.id)])
    setMsgStore((p) => ({ ...p, [c.id]: c }))
    setViewMode('chat')
    setActiveId(c.id)
    return c
  }, [activeConv, activeId, conversations, msgStore, selModel])

  const handleNew = useCallback(async () => { setError(''); try { await createConv() } catch (e) { setError(e.message) } }, [createConv])

  const refreshLocationPermission = useCallback(async () => {
    const state = await queryGeolocationPermission()
    setLocationPermission(state)
    return state
  }, [])

  const handleOpenPrivacyView = useCallback(() => {
    setError('')
    setLocationPermissionMessage('')
    void refreshLocationPermission()
    setViewMode('privacy')
    setSidebarOpen(false)
  }, [refreshLocationPermission])

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

  const requestDeleteConversation = useCallback((conversation) => {
    setDeleteTarget(conversation)
  }, [])

  const startRenameConversation = useCallback((conversation) => {
    setRenamingId(conversation.id)
    setRenamingTitle(conversation.title || '')
    setError('')
  }, [])

  const cancelRenameConversation = useCallback(() => {
    if (renamePending) return
    setRenamingId(null)
    setRenamingTitle('')
  }, [renamePending])

  const submitRenameConversation = useCallback(async (id) => {
    const title = renamingTitle.trim()
    if (!id || !title || renamePending) return
    setRenamePending(true)
    setError('')
    try {
      const response = await api(`/api/conversations/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ title }),
      })
      const payload = await response.json().catch(() => ({}))
      if (response.status === 401) {
        resetAuthState()
        return
      }
      if (!response.ok) throw new Error(payload.detail || '重命名对话失败')
      const summary = makeConversationSummary(payload)
      applyConversationSummary(id, summary)
      setRenamingId(null)
      setRenamingTitle('')
    } catch (err) {
      setError(err.message || '重命名对话失败')
    } finally {
      setRenamePending(false)
    }
  }, [applyConversationSummary, renamePending, renamingTitle, resetAuthState])

  const handleDelete = useCallback(async () => {
    const id = deleteTarget?.id
    if (!id) return
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
      if (activeId === id) setEditingMessage(null)
      setDeleteTarget(null)
    } catch (e) { setError(e.message) }
  }, [activeId, clearConversationStreamState, clearDraftThinkingTimer, conversations, deleteTarget, setConversationTitlePending])

  const handleResetUserData = useCallback(async () => {
    if (userDataClearing) return
    if (hasStreamingConversation) {
      setError('请先等待当前回复结束，再执行一键清空。')
      return
    }

    setError('')
    setUserDataClearing(true)
    try {
      const response = await api('/api/user-data', { method: 'DELETE' })
      const payload = await response.json().catch(() => ({}))
      if (response.status === 401) {
        resetAuthState()
        return
      }
      if (!response.ok) throw new Error(payload.detail || '清空数据失败')

      setConversations([])
      setMsgStore({})
      setActiveId(null)
      setStreamingConversations({})
      setStopPendingConversations({})
      setPendingTitles({})
      setFbPending([])
      setInput('')
      setEditingMessage(null)
      setThinkingEnabled(true)
      setSidebarCollapsed(false)
      setLocationRecommendationEnabled(false)
      setLocationPermissionMessage('')
      setUserDataSummary({ conversation_count: 0, message_count: 0, memory_count: 0 })
      setResetDialogOpen(false)
    } catch (err) {
      setError(err.message || '清空数据失败')
    } finally {
      setUserDataClearing(false)
    }
  }, [hasStreamingConversation, resetAuthState, userDataClearing])

  const handleCopyMessage = useCallback(async (message) => {
    const text = messageTextContent(message)
    if (!text) return
    setError('')
    try {
      const copied = await copyTextToClipboard(text)
      if (!copied) throw new Error('copy failed')
      setCopiedMessageId(message.id)
      setScreenReaderStatus(message.role === 'assistant' ? '回复已复制。' : '消息已复制。')
      if (copiedMessageTimerRef.current) clearTimeout(copiedMessageTimerRef.current)
      copiedMessageTimerRef.current = window.setTimeout(() => {
        setCopiedMessageId(null)
        copiedMessageTimerRef.current = null
      }, 1600)
    } catch {
      setError('复制失败，请检查浏览器剪贴板权限。')
      setScreenReaderStatus('复制失败，请检查浏览器剪贴板权限。')
    }
  }, [])

  const enableLocationRecommendations = useCallback(async () => {
    if (locationPermissionBusy) return
    setLocationPermissionBusy(true)
    setLocationPermissionMessage('')
    try {
      await requestBrowserLocation()
      setLocationPermission('granted')
      setLocationRecommendationEnabled(true)
      setLocationPermissionMessage('已开启。之后你发送新对话时，灵犀会临时使用本次浏览器定位判断是否需要顺路提醒附近食堂或自习地点。')
      void api('/api/recommendations/signal-refresh', { method: 'POST' }).catch(() => {})
    } catch (err) {
      const state = await queryGeolocationPermission()
      setLocationPermission(state)
      setLocationRecommendationEnabled(false)
      setLocationPermissionMessage(refineGeolocationErrorMessage(err.message, state))
    } finally {
      setLocationPermissionBusy(false)
    }
  }, [locationPermissionBusy])

  const disableLocationRecommendations = useCallback(() => {
    setLocationRecommendationEnabled(false)
    setLocationPermissionMessage('已关闭定位智能提醒。浏览器授权状态可在浏览器站点设置中管理。')
  }, [])

  const updateDraft = useCallback((cid, fn) => {
    setMsgStore((s) => {
      const cv = s[cid]; if (!cv) return s
      const ms = [...cv.messages]; const last = ms.at(-1)
      if (!last?.isDraft) return s
      ms[ms.length - 1] = fn(last)
      return { ...s, [cid]: { ...cv, messages: ms } }
    })
  }, [])

  const replaceProvisionalUserMessage = useCallback((cid, message) => {
    if (!message?.id) return
    setMsgStore((s) => {
      const cv = s[cid]
      if (!cv) return s
      const ms = [...(cv.messages ?? [])]
      const existingIndex = ms.findIndex((item) => item.id === message.id)
      if (existingIndex >= 0) {
        ms[existingIndex] = { ...ms[existingIndex], ...message, parts: userTextParts(message.content) }
        return { ...s, [cid]: { ...cv, messages: ms } }
      }
      const draftIndex = ms.findIndex((item) => item.isDraft)
      const candidateIndex = draftIndex > 0 ? draftIndex - 1 : ms.length - 1
      const candidate = ms[candidateIndex]
      if (candidate?.role !== 'user' || !String(candidate.id ?? '').startsWith('u-')) return s
      ms[candidateIndex] = { ...candidate, ...message, parts: userTextParts(message.content) }
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
      const currentDraft = ms.at(-1)
      const nextMessage = msg?.isStopped ? mergeStoppedAssistantWithDraft(msg, currentDraft) : msg
      if (currentDraft?.isDraft) ms[ms.length - 1] = nextMessage; else ms.push(nextMessage)
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
        if (ev === 'user') replaceProvisionalUserMessage(cid, d)
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
        if (ev === 'done') {
          replaceDraft(cid, d.stopped === true ? stoppedAssistant(d.message) : d.message, d.conversation, d.title_pending === true)
          setScreenReaderStatus(d.stopped === true ? '回复已停止，已生成内容已保留。' : '回复已完成。')
        }
        if (ev === 'title') applyConversationSummary(cid, d.conversation)
        if (ev === 'error') {
          throw Object.assign(new Error(d.message || '生成回复失败'), {
            fallback: d.fallback,
            conversation: d.conversation,
          })
        }
      }
    }
  }, [applyConversationSummary, replaceDraft, replaceProvisionalUserMessage, scheduleDraftThinkingIndicator, updateDraft])

  const handleStop = useCallback(async () => {
    const cid = activeId
    if (!cid || !streamingConversations[cid] || stopPendingConversations[cid]) return
    setError('')
    setScreenReaderStatus('正在停止回复，已生成内容会保留。')
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

  const buildTransientMessageContext = useCallback(async ({ firstUserTurn = false } = {}) => {
    if (!locationRecommendationEnabled || !firstUserTurn) return null
    try {
      const location = await requestBrowserLocation({ timeout: 1200, maximumAge: 120000 })
      setLocationPermission('granted')
      return {
        location: {
          ...location,
          timestamp: new Date().toISOString(),
        },
      }
    } catch (err) {
      const state = await queryGeolocationPermission()
      setLocationPermission(state)
      setLocationPermissionMessage(refineGeolocationErrorMessage(err.message, state))
      return null
    }
  }, [locationRecommendationEnabled])

  const sendPrompt = useCallback(async (rawPrompt, options = {}) => {
    const prompt = String(rawPrompt ?? '').trim()
    const rerunMessageId = String(options.rerunMessageId ?? '').trim()
    const isRerun = Boolean(rerunMessageId)
    if (!prompt || (activeId && streamingConversations[activeId])) return
    if (prompt.length > MESSAGE_MAX_LENGTH) {
      setError(`单次消息最多 ${MESSAGE_MAX_LENGTH} 字，请精简后再发送。`)
      composerRef.current?.focus()
      return
    }
    setError('')
    setFailedPrompt(null)
    shouldAutoScrollRef.current = true
    let cid = activeId
    let conv = activeId ? (msgStore[activeId] ?? activeConv) : null
    if (options.clearInput !== false) setInput('')
    if (isRerun && options.clearEditing !== false) setEditingMessage(null)
    try {
      if (!conv && isRerun) {
        throw new Error('当前对话尚未加载，无法重新生成。')
      }
      if (!conv) {
        conv = await createConv()
        cid = conv.id
      } else {
        cid = conv.id
      }
      const firstUserTurn = !isRerun && (conv.messages ?? []).filter((message) => message.role === 'user').length === 0
      const timestamp = new Date().toISOString()
      let pendingMessages
      if (isRerun) {
        const sourceMessages = conv.messages ?? []
        const targetIndex = sourceMessages.findIndex((message) => message.id === rerunMessageId && message.role === 'user')
        if (targetIndex < 0) throw new Error('未找到要重新生成的问题。')
        const targetMessage = sourceMessages[targetIndex]
        const updatedUserMessage = {
          ...targetMessage,
          content: prompt,
          timestamp: messageTextContent(targetMessage) === prompt ? targetMessage.timestamp : timestamp,
          parts: userTextParts(prompt),
        }
        pendingMessages = [...sourceMessages.slice(0, targetIndex), updatedUserMessage, draftAssistant()]
      } else {
        const um = { id: `u-${createUuid()}`, role: 'user', content: prompt, timestamp, parts: userTextParts(prompt) }
        pendingMessages = [...(conv.messages ?? []), um, draftAssistant()]
      }
      const pendingConversation = { ...conv, model: selModel, updated_at: timestamp, messages: pendingMessages }
      setConversationStopPending(cid, false)
      setConversationStreaming(cid, true)
      setMsgStore((s) => ({ ...s, [cid]: pendingConversation }))
      updateSummary(makeConversationSummary(pendingConversation))
      setScreenReaderStatus(isRerun ? '正在重新生成回复。' : '消息已发送，正在生成回复。')
      const transientContext = await buildTransientMessageContext({ firstUserTurn })
      const requestBody = {
        content: prompt,
        model: selModel,
        thinking_enabled: thinkingEnabled,
        ...(isRerun ? { rerun_message_id: rerunMessageId } : {}),
        ...(transientContext ? { context: transientContext } : {}),
      }
      const r = await api(`/api/conversations/${cid}/messages`, {
        method: 'POST',
        body: JSON.stringify(requestBody),
      })
      if (!r.ok) throw new Error(await readApiError(r, '发送消息失败', '发送消息过快，请稍后再试。'))
      if (!r.body) throw new Error('响应流不可用，请稍后再试。')
      await readSSE(r, cid)
      setFailedPrompt(null)
    } catch (err) {
      const message = err.message || '发送失败，请稍后重试。'
      setError(message)
      if (isRerun) {
        if (options.restoreEditOnFailure) {
          setEditingMessage({ id: rerunMessageId, content: prompt })
          setInput(prompt)
          requestAnimationFrame(() => composerRef.current?.focus())
        }
      } else {
        setFailedPrompt({ prompt, message })
      }
      if (cid && err.fallback && err.conversation) {
        replaceDraft(cid, err.fallback, err.conversation)
      } else if (cid) {
        clearDraftThinkingTimer(cid)
        const fallback = localError(err.message || '暂时无法生成回复，请稍后再试。')
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
  }, [activeId, activeConv, msgStore, selModel, thinkingEnabled, buildTransientMessageContext, clearConversationStreamState, clearDraftThinkingTimer, createConv, readSSE, refreshAuthState, replaceDraft, setConversationStopPending, setConversationStreaming, streamingConversations, updateDraft, updateSummary])

  const handleSubmit = useCallback((event) => {
    event.preventDefault()
    if (editingMessage?.id) {
      void sendPrompt(input, {
        rerunMessageId: editingMessage.id,
        clearInput: true,
        restoreEditOnFailure: true,
      })
      return
    }
    void sendPrompt(input)
  }, [editingMessage, input, sendPrompt])

  const restoreFailedPrompt = useCallback(() => {
    if (!failedPrompt?.prompt) return
    setInput(failedPrompt.prompt)
    setFailedPrompt(null)
    setError('')
    requestAnimationFrame(() => composerRef.current?.focus())
  }, [failedPrompt])

  const retryFailedPrompt = useCallback(() => {
    if (!failedPrompt?.prompt) return
    void sendPrompt(failedPrompt.prompt)
  }, [failedPrompt, sendPrompt])

  const startEditMessage = useCallback((message) => {
    if (activeId && streamingConversations[activeId]) return
    const text = messageTextContent(message)
    if (!text) return
    setEditingMessage({ id: message.id, content: text })
    setInput(text)
    setError('')
    setFailedPrompt(null)
    setScreenReaderStatus('已进入消息修改模式，发送后会覆盖这条问题之后的所有内容。')
    requestAnimationFrame(() => composerRef.current?.focus())
  }, [activeId, streamingConversations])

  const cancelEditMessage = useCallback(() => {
    setEditingMessage(null)
    setInput('')
    setScreenReaderStatus('已取消消息修改。')
    requestAnimationFrame(() => composerRef.current?.focus())
  }, [])

  const regenerateMessage = useCallback((message) => {
    const cid = activeId
    const conv = cid ? (msgStore[cid] ?? activeConv) : null
    if (!cid || !conv || streamingConversations[cid]) return
    const userMessage = previousUserMessage(conv.messages ?? [], message.id)
    const prompt = messageTextContent(userMessage)
    if (!userMessage?.id || !prompt) {
      setError('未找到这条回复对应的问题，无法重新生成。')
      return
    }
    setError('')
    setFailedPrompt(null)
    setScreenReaderStatus('正在重新生成回复。')
    void sendPrompt(prompt, { rerunMessageId: userMessage.id, clearInput: false })
  }, [activeConv, activeId, msgStore, sendPrompt, streamingConversations])

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

  const applyQuickPrompt = useCallback((prompt) => {
    setInput(prompt)
    setFailedPrompt(null)
    setError('')
    requestAnimationFrame(() => composerRef.current?.focus())
  }, [])

  // --- Auth check ---
  if (!authChecked) return <div className="loading-screen"><div className="loading-spinner" /><p>正在加载…</p></div>
  if (!user) return <LoginPage onLogin={handleLogin} />

  // --- Main UI ---
  return (
    <div className={`app-shell ${sidebarCollapsed ? 'app-shell--sidebar-collapsed' : ''}`}>
      <a className="skip-link" href="#main-content">跳到聊天内容</a>
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {screenReaderStatus}
      </div>
      <IconButton
        className="sidebar-toggle"
        label="打开侧栏"
        onClick={() => setSidebarOpen((v) => !v)}
        aria-controls="app-sidebar"
        aria-expanded={sidebarOpen}
      >
        <Menu size={20} aria-hidden="true" />
      </IconButton>
      {sidebarOpen && <button type="button" className="sidebar-scrim" aria-label="关闭侧栏" onClick={() => setSidebarOpen(false)} />}

      <aside id="app-sidebar" className={`sidebar ${sidebarOpen ? 'sidebar--open' : ''} ${sidebarCollapsed ? 'sidebar--collapsed' : ''}`} aria-label="应用侧栏">
        <div className="sidebar-top">
          <div className="brand-card">
            <img src="/assets/FZU.png" alt="福州大学" className="brand-logo" />
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
            <IconButton className="logout-btn" label="退出登录" onClick={handleLogout}>
              <LogOut size={17} aria-hidden="true" />
            </IconButton>
          </div>

          {needsEduRelogin ? (
            <EduReloginPanel
              message={eduError}
              studentId={user.user_id}
              onSubmit={handleEduRelogin}
            />
          ) : eduError ? <div className="edu-warn">{eduError}</div> : null}

          <button className="new-chat-btn" onClick={handleNew} type="button">
            <MessageSquarePlus size={18} aria-hidden="true" /> 新建对话
          </button>

          <button
            className={`sidebar-link-btn ${isPrivacyView ? 'sidebar-link-btn--active' : ''}`}
            onClick={handleOpenPrivacyView}
            type="button"
          >
            <ShieldCheck size={16} aria-hidden="true" /> 隐私与数据
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
          <label className="convo-search" htmlFor="conversation-search">
            <Search size={15} aria-hidden="true" />
            <input
              id="conversation-search"
              type="search"
              value={conversationQuery}
              onChange={(event) => setConversationQuery(event.target.value)}
              placeholder="搜索标题或内容"
            />
          </label>
          <div className="convo-list">
            {conversations.length === 0
              ? <div className="empty-hint">暂无历史对话</div>
              : filteredConversations.length === 0
                ? <div className="empty-hint">没有匹配的对话</div>
                : filteredConversations.map((c) => (
                <div key={c.id} className={`convo-item ${c.id === activeId ? 'convo-item--active' : ''}`}>
                  {renamingId === c.id ? (
                    <form
                      className="convo-rename"
                      onSubmit={(event) => {
                        event.preventDefault()
                        void submitRenameConversation(c.id)
                      }}
                    >
                      <input
                        value={renamingTitle}
                        onChange={(event) => setRenamingTitle(event.target.value)}
                        maxLength={20}
                        aria-label="对话标题"
                        autoFocus
                      />
                      <IconButton label="保存标题" type="submit" variant="success" disabled={renamePending || !renamingTitle.trim()}>
                        <Check size={15} aria-hidden="true" />
                      </IconButton>
                      <IconButton label="取消重命名" onClick={cancelRenameConversation} disabled={renamePending}>
                        <X size={15} aria-hidden="true" />
                      </IconButton>
                    </form>
                  ) : (
                    <>
                      <button type="button" className="convo-select" onClick={() => { setViewMode('chat'); setActiveId(c.id); setSidebarOpen(false) }}>
                        <div className="convo-item-body">
                          <strong className={`convo-title ${pendingTitles[c.id] ? 'convo-title--pending' : ''}`.trim()} aria-label={pendingTitles[c.id] ? '正在生成标题' : c.title}>
                            {pendingTitles[c.id] ? <PendingTitle compact /> : c.title}
                          </strong>
                          <span>{c.preview || '等待第一条消息…'}</span>
                        </div>
                      </button>
                      <div className="convo-actions">
                        <IconButton label={`重命名${c.title}`} className="convo-action" onClick={() => startRenameConversation(c)}>
                          <Pencil size={14} aria-hidden="true" />
                        </IconButton>
                        <IconButton label={`删除${c.title}`} className="convo-action convo-action--danger" onClick={() => requestDeleteConversation(c)}>
                          <Trash2 size={14} aria-hidden="true" />
                        </IconButton>
                      </div>
                    </>
                  )}
                </div>
              ))
            }
          </div>
        </div>
      </aside>

      <main id="main-content" className="chat-area" aria-labelledby="chat-heading" tabIndex={-1}>
        <header className="chat-header">
          <div className="chat-header-left">
            <IconButton
              className="sidebar-desktop-toggle"
              onClick={toggleDesktopSidebar}
              label={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
              aria-expanded={!sidebarCollapsed}
            >
              {sidebarCollapsed ? <PanelLeftOpen size={20} aria-hidden="true" /> : <PanelLeftClose size={20} aria-hidden="true" />}
            </IconButton>
            <div className="chat-header-copy">
              <h2 id="chat-heading" className={`chat-header-title ${!isPrivacyView && activeConv && pendingTitles[activeConv.id] ? 'chat-header-title--pending' : ''}`.trim()} aria-label={isPrivacyView ? '隐私与数据' : (activeConv && pendingTitles[activeConv.id] ? '正在生成标题' : (activeConv?.title ?? '新的对话'))}>
                {isPrivacyView ? '隐私与数据' : (activeConv && pendingTitles[activeConv.id] ? <PendingTitle /> : (activeConv?.title ?? '新的对话'))}
              </h2>
              <p>{isPrivacyView ? '查看隐私政策、数据统计和一键清空入口' : '福州大学知识库 · 联网搜索 · 教务系统'}</p>
            </div>
          </div>
          {!isPrivacyView && (
            <div className="chat-header-badges">
              <div className="chat-header-badge">{models.find((m) => m.id === selModel)?.label ?? selModel}</div>
              <div className={`chat-header-badge chat-header-badge--thinking ${thinkingEnabled ? 'chat-header-badge--thinking-on' : ''}`}>
                {thinkingEnabled ? '思考开启' : '思考关闭'}
              </div>
            </div>
          )}
        </header>

        {isPrivacyView ? (
          <PrivacyPolicyView
            summary={userDataSummary}
            loading={userDataLoading}
            clearing={userDataClearing}
            resetDisabled={userDataLoading || userDataClearing || hasStreamingConversation}
            locationEnabled={locationRecommendationEnabled}
            locationPermission={locationPermission}
            locationBusy={locationPermissionBusy}
            locationMessage={locationPermissionMessage}
            onReload={() => void loadUserDataSummary()}
            onReset={() => setResetDialogOpen(true)}
            onEnableLocation={() => void enableLocationRecommendations()}
            onDisableLocation={disableLocationRecommendations}
            onRefreshLocationPermission={() => void refreshLocationPermission()}
            error={error}
          />
        ) : (
          <>
        <section
          id="message-list"
          className={`msg-list ${activeMsgs.length === 0 ? 'msg-list--empty' : ''}`.trim()}
          ref={msgListRef}
          onScroll={syncAutoScrollState}
          onWheel={handleMsgListWheel}
          role="log"
          aria-label="聊天消息"
          aria-live="polite"
          aria-relevant="additions text"
          aria-atomic="false"
          aria-busy={isActiveConversationStreaming}
        >
          {activeMsgs.length === 0 ? (
            <EmptyChatState
              message={EMPTY_MSG}
              onPrompt={applyQuickPrompt}
            />
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
                m.isErrorFallback ? 'msg-bubble--error' : '',
                m.isStopped ? 'msg-bubble--stopped' : '',
              ].filter(Boolean).join(' ')

              return (
                <article
                  key={m.id}
                  className={`msg-row ${m.role === 'user' ? 'msg-row--user' : ''}`}
                  aria-label={`${m.role === 'user' ? user.display_name : '福大灵犀'}的消息`}
                >
                  <div className={`avatar ${m.role === 'user' ? 'avatar--user' : 'avatar--bot'}`} aria-hidden="true">
                    {m.role === 'user' ? (user.display_name?.charAt(0) || 'U') : <img src="/assets/FZU.png" alt="" />}
                  </div>
                  <div className="msg-body">
                    <div className="msg-meta">
                      <span>{m.role === 'user' ? user.display_name : '福大灵犀'}</span>
                      <time dateTime={m.timestamp}>{fmt(m.timestamp)}</time>
                      {m.isDraft && <span className="msg-status-pill">生成中</span>}
                      {m.isStopped && <span className="msg-status-pill msg-status-pill--stopped">已停止</span>}
                      {m.isErrorFallback && <span className="msg-status-pill msg-status-pill--error">生成失败</span>}
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
                    {(!m.isDraft || canFeedback(m)) && (
                      <div className={`message-actions ${m.role === 'user' ? 'message-actions--user' : ''}`}>
                        {!m.isDraft && (
                          <button
                            type="button"
                            className="message-action-btn"
                            onClick={() => void handleCopyMessage(m)}
                            aria-label={copiedMessageId === m.id ? '已复制' : m.role === 'assistant' ? '复制回复' : '复制消息'}
                            title={copiedMessageId === m.id ? '已复制' : m.role === 'assistant' ? '复制回复' : '复制消息'}
                          >
                            {copiedMessageId === m.id ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
                          </button>
                        )}
                        {m.role === 'assistant' && !m.isDraft && (
                          <button
                            type="button"
                            className="message-action-btn"
                            onClick={() => regenerateMessage(m)}
                            disabled={isActiveConversationStreaming}
                            aria-label="重新生成回复"
                            title="重新生成回复并替换后续对话"
                          >
                            <RefreshCw size={14} aria-hidden="true" />
                          </button>
                        )}
                        {m.role === 'user' && !m.isDraft && (
                          <button
                            type="button"
                            className="message-action-btn"
                            onClick={() => startEditMessage(m)}
                            disabled={isActiveConversationStreaming}
                            aria-label="修改这条消息并覆盖之后的所有内容"
                            title="修改这条消息并覆盖之后的所有内容"
                          >
                            <Pencil size={14} aria-hidden="true" />
                          </button>
                        )}
                        {canFeedback(m) && (
                          <>
                            <IconButton
                              label={m.feedback === 'up' ? '取消赞同反馈' : '这条回复有帮助'}
                              disabled={fbPending.includes(m.id)}
                              className={m.feedback === 'up' ? 'fb-btn fb-btn--on' : 'fb-btn'}
                              onClick={() => void handleFeedback(m.id, 'up')}
                            >
                              <ThumbsUp size={15} aria-hidden="true" />
                            </IconButton>
                            <IconButton
                              label={m.feedback === 'down' ? '取消负面反馈' : '这条回复需要改进'}
                              disabled={fbPending.includes(m.id)}
                              className={m.feedback === 'down' ? 'fb-btn fb-btn--on fb-btn--down-on' : 'fb-btn'}
                              onClick={() => void handleFeedback(m.id, 'down')}
                            >
                              <ThumbsDown size={15} aria-hidden="true" />
                            </IconButton>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                </article>
              )
            })
          )}
        </section>

        <ChatComposer
          composerRef={composerRef}
          disabled={!input.trim()}
          editingMessage={editingMessage}
          error={error}
          failedPrompt={failedPrompt}
          input={input}
          inputLength={inputLength}
          inputNearLimit={inputNearLimit}
          isStopPending={isActiveConversationStopPending}
          isStreaming={isActiveConversationStreaming}
          maxLength={MESSAGE_MAX_LENGTH}
          onChange={(value) => {
            setInput(value)
            if (failedPrompt) setFailedPrompt(null)
          }}
          onCancelEdit={cancelEditMessage}
          onRestoreFailedPrompt={restoreFailedPrompt}
          onRetryFailedPrompt={retryFailedPrompt}
          onScrollBottom={scrollMessagesToBottom}
          onStop={() => { void handleStop() }}
          onSubmit={handleSubmit}
          showScrollBottom={showScrollBottom}
          statusText={composerStatusText}
        />
          </>
        )}
      </main>
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="删除这个对话？"
        description="删除后会从历史记录中移除该对话，相关消息也会一起删除。"
        confirmText="删除"
        danger
        details={deleteTarget ? <span>对话：{deleteTarget.title || '未命名对话'}</span> : null}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => void handleDelete()}
      />
      <ConfirmDialog
        open={resetDialogOpen}
        title="清空已保存数据？"
        description="这会删除服务器上已保存的对话历史、长期记忆，并恢复本地界面设置默认值。此操作不可撤销。"
        confirmText="一键清空"
        danger
        busy={userDataClearing}
        details={(
          <div className="reset-summary">
            <span>历史对话：{userDataSummary?.conversation_count ?? 0}</span>
            <span>消息总数：{userDataSummary?.message_count ?? 0}</span>
            <span>长期记忆：{userDataSummary?.memory_count ?? 0}</span>
          </div>
        )}
        onCancel={() => {
          if (!userDataClearing) setResetDialogOpen(false)
        }}
        onConfirm={() => void handleResetUserData()}
      />
    </div>
  )
}

export default App
