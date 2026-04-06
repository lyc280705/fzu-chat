import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const EMPTY_MSG = '你好呀！我是福大灵犀，你可以向我提问关于福州大学的任何问题，也可以查询你的成绩和课表哦～'

const TOOL_ICONS = {
  retrieve: '📚',
  bocha_websearch_tool: '🌐',
  query_grades: '📊',
  query_courses: '📅',
  query_student_info: '👤',
  query_exam_scores: '📝',
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

const draftAssistant = () => ({
  id: `draft-${crypto.randomUUID()}`,
  role: 'assistant',
  content: '',
  parts: [],
  feedback: null,
  timestamp: new Date().toISOString(),
  isDraft: true,
})

const localError = (c = '暂时无法生成回复，请稍后再试。') => ({
  id: `err-${crypto.randomUUID()}`,
  role: 'assistant',
  content: c,
  parts: [{ type: 'text', content: c }],
  feedback: null,
  timestamp: new Date().toISOString(),
  isLocalOnly: true,
})

const canFeedback = (m) => m.role === 'assistant' && !m.isDraft && !m.isLocalOnly
const normMsgs = (msgs = []) =>
  msgs.map((m) => ({
    ...m,
    isLocalOnly: m.isLocalOnly ?? false,
    parts: m.parts?.length ? m.parts : m.content ? [{ type: 'text', content: m.content }] : [],
  }))

/* ------------------------------------------------------------------ */
/*  API helpers (inject auth token)                                    */
/* ------------------------------------------------------------------ */

const api = (url, opts = {}) => {
  const token = localStorage.getItem('fzu_token')
  const headers = { ...(opts.headers || {}) }
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (opts.body && typeof opts.body === 'string') headers['Content-Type'] = 'application/json'
  return fetch(url, { ...opts, headers })
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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ student_id: studentId.trim(), password: password.trim(), student_type: studentType }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || '登录失败')
      }
      const data = await res.json()
      localStorage.setItem('fzu_token', data.token)
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
              <option value="graduate">研究生</option>
            </select>
          </label>
          <button type="submit" className="login-btn" disabled={loading || !studentId.trim() || !password.trim()}>
            {loading ? '登录中…' : '登 录'}
          </button>
        </form>
        <p className="login-footer">密码仅用于教务系统认证，不会被存储</p>
      </div>
    </div>
  )
}

/* ================================================================== */
/*  Grade Table                                                        */
/* ================================================================== */

function GradeTable({ data }) {
  if (!Array.isArray(data) || data.length === 0) return null
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>学期</th><th>课程</th><th>学分</th><th>成绩</th><th>绩点</th>
          </tr>
        </thead>
        <tbody>
          {data.map((r, i) => (
            <tr key={i}>
              <td>{r.semester}</td><td>{r.name}</td><td>{r.credits}</td><td>{r.score}</td><td>{r.gpa}</td>
            </tr>
          ))}
        </tbody>
      </table>
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

/* ================================================================== */
/*  Tool Card                                                          */
/* ================================================================== */

function ToolCard({ part }) {
  const icon = TOOL_ICONS[part.tool_name] || '🔧'
  const isRunning = part.status === 'running'

  const renderData = () => {
    if (!part.data) return null
    switch (part.tool_name) {
      case 'query_grades':
        return <GradeTable data={part.data} />
      case 'query_courses':
        return <CourseTable data={part.data} />
      case 'query_exam_scores':
        return <ExamTable data={part.data} />
      case 'query_student_info':
        return <StudentInfoCard data={part.data} />
      default:
        return null
    }
  }

  return (
    <div className={`tool-card ${isRunning ? 'tool-card--running' : 'tool-card--done'}`}>
      <div className="tool-card-header">
        <span className="tool-card-icon">{icon}</span>
        <span className="tool-card-title">{part.status_label}</span>
        {isRunning && <span className="tool-spinner" />}
      </div>
      {part.query && <div className="tool-card-query">{part.query}</div>}
      {renderData()}
      {part.urls?.length > 0 && (
        <div className="tool-links">
          {part.urls.map((u) => (
            <a key={u} href={u} target="_blank" rel="noreferrer">{u}</a>
          ))}
        </div>
      )}
    </div>
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
  const [selModel, setSelModel] = useState('qwen-max-latest')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [fbPending, setFbPending] = useState([])
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const endRef = useRef(null)

  const activeConv = useMemo(() => conversations.find((c) => c.id === activeId) ?? null, [activeId, conversations])
  const activeMsgs = useMemo(() => normMsgs(msgStore[activeId]?.messages ?? []), [activeId, msgStore])

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [activeMsgs])

  // --- Check existing token on mount ---
  useEffect(() => {
    const token = localStorage.getItem('fzu_token')
    if (!token) { setAuthChecked(true); return }
    api('/api/auth/me')
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((u) => { setUser(u); setAuthChecked(true) })
      .catch(() => { localStorage.removeItem('fzu_token'); setAuthChecked(true) })
  }, [])

  // --- Bootstrap after login ---
  useEffect(() => {
    if (!user) return
    const go = async () => {
      try {
        const [mr, cr] = await Promise.all([api('/api/models'), api('/api/conversations')])
        if (!mr.ok || !cr.ok) throw new Error('初始化失败')
        const [mp, cp] = await Promise.all([mr.json(), cr.json()])
        setModels(mp)
        if (mp.length) setSelModel(mp[0].id)
        setConversations(cp)
        if (cp.length) setActiveId(cp[0].id)
      } catch (e) { setError(e.message) }
    }
    go()
  }, [user])

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
    if (m) setSelModel(m)
  }, [activeConv, activeId, msgStore])

  // --- Handlers ---
  const handleLogin = useCallback((u, eduErr) => { setUser(u); setEduError(eduErr) }, [])

  const handleLogout = useCallback(async () => {
    await api('/api/auth/logout', { method: 'POST' }).catch(() => {})
    localStorage.removeItem('fzu_token')
    setUser(null)
    setConversations([])
    setMsgStore({})
    setActiveId(null)
  }, [])

  const createConv = useCallback(async () => {
    const r = await api('/api/conversations', { method: 'POST', body: JSON.stringify({ model: selModel }) })
    if (!r.ok) throw new Error('创建对话失败')
    const c = await r.json()
    const sm = { id: c.id, title: c.title, model: c.model, created_at: c.created_at, updated_at: c.updated_at, preview: '', message_count: 0 }
    setConversations((p) => [sm, ...p])
    setMsgStore((p) => ({ ...p, [c.id]: c }))
    setActiveId(c.id)
    return c.id
  }, [selModel])

  const handleNew = useCallback(async () => { setError(''); try { await createConv() } catch (e) { setError(e.message) } }, [createConv])

  const handleDelete = useCallback(async (id) => {
    setError('')
    try {
      const r = await api(`/api/conversations/${id}`, { method: 'DELETE' })
      if (!r.ok) throw new Error('删除对话失败')
      setConversations((p) => p.filter((c) => c.id !== id))
      setMsgStore((p) => { const n = { ...p }; delete n[id]; return n })
      if (activeId === id) {
        setActiveId(() => { const f = conversations.find((c) => c.id !== id); return f?.id ?? null })
      }
    } catch (e) { setError(e.message) }
  }, [activeId, conversations])

  const updateSummary = useCallback((sm) => {
    setConversations((p) => [sm, ...p.filter((c) => c.id !== sm.id)])
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

  const replaceDraft = useCallback((cid, msg, sm) => {
    setMsgStore((s) => {
      const cv = s[cid]; if (!cv) return s
      const ms = [...cv.messages]
      if (ms.at(-1)?.isDraft) ms[ms.length - 1] = msg; else ms.push(msg)
      return { ...s, [cid]: { ...cv, title: sm.title, updated_at: sm.updated_at, model: sm.model, messages: ms } }
    })
    updateSummary(sm)
  }, [updateSummary])

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
        if (ev === 'chunk') updateDraft(cid, (m) => ({ ...m, content: m.content + d.delta, parts: [{ type: 'text', content: m.content + d.delta }, ...m.parts.filter((p) => p.type === 'tool')] }))
        if (ev === 'tool_call') updateDraft(cid, (m) => ({ ...m, parts: [{ type: 'text', content: m.content }, ...m.parts.filter((p) => p.type === 'tool'), d].filter((p) => p.type !== 'text' || p.content) }))
        if (ev === 'tool_result') updateDraft(cid, (m) => ({ ...m, parts: m.parts.map((p) => (p.type === 'tool' && p.tool_id === d.tool_id ? d : p)) }))
        if (ev === 'done') replaceDraft(cid, d.message, d.conversation)
        if (ev === 'error') throw new Error(d.message || '生成回复失败')
      }
    }
  }, [updateDraft, replaceDraft])

  const handleSubmit = useCallback(async (e) => {
    e.preventDefault()
    if (!input.trim() || sending) return
    setSending(true); setError('')
    const prompt = input.trim()
    let cid = activeId
    setInput('')
    try {
      cid ??= await createConv()
      const um = { id: `u-${crypto.randomUUID()}`, role: 'user', content: prompt, timestamp: new Date().toISOString(), parts: [{ type: 'text', content: prompt }] }
      setMsgStore((s) => {
        const base = s[cid] ?? { id: cid, title: '新对话', model: selModel, messages: [] }
        return { ...s, [cid]: { ...base, model: selModel, messages: [...base.messages, um, draftAssistant()] } }
      })
      const r = await api(`/api/conversations/${cid}/messages`, { method: 'POST', body: JSON.stringify({ content: prompt, model: selModel }) })
      if (!r.ok || !r.body) throw new Error('发送消息失败')
      await readSSE(r, cid)
    } catch (err) {
      setError(err.message)
      const fallback = localError()
      if (cid) updateDraft(cid, (m) => ({ ...fallback, id: m.id, timestamp: m.timestamp }))
    } finally { setSending(false) }
  }, [input, sending, activeId, selModel, createConv, readSSE, updateDraft])

  const handleFeedback = useCallback(async (mid, fb) => {
    const cid = activeId
    if (!cid || fbPending.includes(mid)) return
    const cv = msgStore[cid]; const tm = cv?.messages.find((m) => m.id === mid)
    if (!tm || !canFeedback(tm)) return
    const prev = tm.feedback ?? null
    setFbPending((p) => [...p, mid])
    setMsgStore((s) => ({ ...s, [cid]: { ...s[cid], messages: s[cid].messages.map((m) => (m.id === mid ? { ...m, feedback: fb } : m)) } }))
    try {
      const r = await api(`/api/conversations/${cid}/feedback`, { method: 'POST', body: JSON.stringify({ message_id: mid, feedback: fb }) })
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
    <div className="app-shell">
      {/* Mobile toggle */}
      <button className="sidebar-toggle" onClick={() => setSidebarOpen((v) => !v)} type="button">☰</button>

      <aside className={`sidebar ${sidebarOpen ? 'sidebar--open' : ''}`}>
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
                {user.edu_authenticated ? ' · 教务已连接' : ''}</span>
            </div>
            <button className="logout-btn" onClick={handleLogout} type="button" title="退出登录">⏻</button>
          </div>

          {eduError && <div className="edu-warn">{eduError}</div>}

          <button className="new-chat-btn" onClick={handleNew} type="button">
            <span className="plus-icon">+</span> 新建对话
          </button>
        </div>

        <div className="sidebar-model">
          <label htmlFor="model-sel">模型</label>
          <select id="model-sel" value={selModel} onChange={(e) => setSelModel(e.target.value)}>
            {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </div>

        <div className="sidebar-convos">
          <div className="section-title">对话历史</div>
          <div className="convo-list">
            {conversations.length === 0
              ? <div className="empty-hint">暂无历史对话</div>
              : conversations.map((c) => (
                <button key={c.id} type="button" className={`convo-item ${c.id === activeId ? 'convo-item--active' : ''}`} onClick={() => { setActiveId(c.id); setSidebarOpen(false) }}>
                  <div className="convo-item-body">
                    <strong>{c.title}</strong>
                    <span>{c.preview || '等待第一条消息…'}</span>
                  </div>
                  <span className="convo-del" onClick={(ev) => { ev.stopPropagation(); void handleDelete(c.id) }}>×</span>
                </button>
              ))
            }
          </div>
        </div>
      </aside>

      <main className="chat-area">
        <header className="chat-header">
          <div className="chat-header-left">
            <h2>{activeConv?.title ?? '新的对话'}</h2>
            <p>福州大学知识库 · 联网搜索 · 教务系统</p>
          </div>
          <div className="chat-header-badge">{models.find((m) => m.id === selModel)?.label ?? selModel}</div>
        </header>

        <section className="msg-list">
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
            activeMsgs.map((m) => (
              <article key={m.id} className={`msg-row ${m.role === 'user' ? 'msg-row--user' : ''}`}>
                <div className={`avatar ${m.role === 'user' ? 'avatar--user' : 'avatar--bot'}`}>
                  {m.role === 'user' ? (user.display_name?.charAt(0) || 'U') : <img src="/assets/FZU.png" alt="bot" />}
                </div>
                <div className="msg-body">
                  <div className="msg-meta">
                    <span>{m.role === 'user' ? user.display_name : '福大灵犀'}</span>
                    <time>{fmt(m.timestamp)}</time>
                  </div>
                  <div className="msg-bubble">
                    {m.parts.filter((p) => p.type === 'text' && p.content).map((p, i) => (
                      <p key={`${m.id}-t-${i}`}>{p.content}</p>
                    ))}
                    {m.parts.filter((p) => p.type === 'tool').map((p) => (
                      <ToolCard key={p.tool_id} part={p} />
                    ))}
                    {m.isDraft && !m.content && m.parts.filter((p) => p.type === 'tool').length === 0 && (
                      <div className="typing-indicator"><span /><span /><span /></div>
                    )}
                  </div>
                  {canFeedback(m) && (
                    <div className="feedback-row">
                      <button type="button" disabled={fbPending.includes(m.id)} className={m.feedback === 'up' ? 'fb-btn fb-btn--on' : 'fb-btn'} onClick={() => void handleFeedback(m.id, 'up')}>👍</button>
                      <button type="button" disabled={fbPending.includes(m.id)} className={m.feedback === 'down' ? 'fb-btn fb-btn--on' : 'fb-btn'} onClick={() => void handleFeedback(m.id, 'down')}>👎</button>
                    </div>
                  )}
                </div>
              </article>
            ))
          )}
          <div ref={endRef} />
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
            <button className="send-btn" type="submit" disabled={sending || !input.trim()}>
              {sending ? <span className="send-spinner" /> : '➤'}
            </button>
          </form>
        </footer>
      </main>
    </div>
  )
}

export default App
