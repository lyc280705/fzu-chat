import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

const EMPTY_ASSISTANT_MESSAGE = '你好呀！我是福大灵犀，很高兴继续帮你查询福州大学相关信息～'

const formatTime = (value) => {
  if (!value) {
    return ''
  }

  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    month: 'short',
    day: 'numeric',
  }).format(new Date(value))
}

const createDraftAssistant = () => ({
  id: `draft-${crypto.randomUUID()}`,
  role: 'assistant',
  content: '',
  parts: [],
  feedback: null,
  timestamp: new Date().toISOString(),
  isDraft: true,
})

const normalizeMessages = (messages = []) =>
  messages.map((message) => ({
    ...message,
    parts:
      message.parts && message.parts.length > 0
        ? message.parts
        : message.content
          ? [{ type: 'text', content: message.content }]
          : [],
  }))

function App() {
  const [models, setModels] = useState([])
  const [conversations, setConversations] = useState([])
  const [activeConversationId, setActiveConversationId] = useState(null)
  const [messagesByConversation, setMessagesByConversation] = useState({})
  const [input, setInput] = useState('')
  const [selectedModel, setSelectedModel] = useState('qwen-max-latest')
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const messagesEndRef = useRef(null)

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeConversationId) ?? null,
    [activeConversationId, conversations],
  )

  const activeMessages = useMemo(
    () => normalizeMessages(messagesByConversation[activeConversationId]?.messages ?? []),
    [activeConversationId, messagesByConversation],
  )

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [activeMessages])

  useEffect(() => {
    const bootstrap = async () => {
      try {
        const [modelsResponse, conversationsResponse] = await Promise.all([
          fetch('/api/models'),
          fetch('/api/conversations'),
        ])

        if (!modelsResponse.ok || !conversationsResponse.ok) {
          throw new Error('初始化失败')
        }

        const [modelsPayload, conversationsPayload] = await Promise.all([
          modelsResponse.json(),
          conversationsResponse.json(),
        ])

        setModels(modelsPayload)
        if (modelsPayload.length > 0) {
          setSelectedModel(modelsPayload[0].id)
        }

        setConversations(conversationsPayload)
        if (conversationsPayload.length > 0) {
          setActiveConversationId(conversationsPayload[0].id)
        }
      } catch (bootstrapError) {
        setError(bootstrapError.message)
      } finally {
        setLoading(false)
      }
    }

    bootstrap()
  }, [])

  useEffect(() => {
    if (!activeConversationId || messagesByConversation[activeConversationId]) {
      return
    }

    const loadConversation = async () => {
      try {
        const response = await fetch(`/api/conversations/${activeConversationId}`)
        if (!response.ok) {
          throw new Error('加载对话失败')
        }

        const payload = await response.json()
        setMessagesByConversation((current) => ({
          ...current,
          [activeConversationId]: payload,
        }))
        setSelectedModel(payload.model)
      } catch (loadError) {
        setError(loadError.message)
      }
    }

    loadConversation()
  }, [activeConversationId, messagesByConversation])

  const createConversation = async () => {
    const response = await fetch('/api/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: selectedModel }),
    })

    if (!response.ok) {
      throw new Error('创建对话失败')
    }

    const conversation = await response.json()
    const summary = {
      id: conversation.id,
      title: conversation.title,
      model: conversation.model,
      created_at: conversation.created_at,
      updated_at: conversation.updated_at,
      preview: '',
      message_count: 0,
    }

    setConversations((current) => [summary, ...current])
    setMessagesByConversation((current) => ({
      ...current,
      [conversation.id]: conversation,
    }))
    setActiveConversationId(conversation.id)
    return conversation.id
  }

  const handleNewConversation = async () => {
    setError('')
    try {
      await createConversation()
    } catch (createError) {
      setError(createError.message)
    }
  }

  const handleDeleteConversation = async (conversationId) => {
    setError('')
    try {
      const response = await fetch(`/api/conversations/${conversationId}`, { method: 'DELETE' })
      if (!response.ok) {
        throw new Error('删除对话失败')
      }

      setConversations((current) => current.filter((conversation) => conversation.id !== conversationId))
      setMessagesByConversation((current) => {
        const next = { ...current }
        delete next[conversationId]
        return next
      })

      if (activeConversationId === conversationId) {
        const fallback = conversations.find((conversation) => conversation.id !== conversationId)
        setActiveConversationId(fallback?.id ?? null)
      }
    } catch (deleteError) {
      setError(deleteError.message)
    }
  }

  const updateConversationSummary = (summary) => {
    setConversations((current) => {
      const filtered = current.filter((conversation) => conversation.id !== summary.id)
      return [summary, ...filtered]
    })
  }

  const updateDraftMessage = (conversationId, updater) => {
    setMessagesByConversation((current) => {
      const conversation = current[conversationId]
      if (!conversation) {
        return current
      }

      const messages = [...conversation.messages]
      const lastMessage = messages.at(-1)
      if (!lastMessage || !lastMessage.isDraft) {
        return current
      }

      messages[messages.length - 1] = updater(lastMessage)
      return {
        ...current,
        [conversationId]: {
          ...conversation,
          messages,
        },
      }
    })
  }

  const replaceDraftMessage = (conversationId, nextMessage, summary) => {
    setMessagesByConversation((current) => {
      const conversation = current[conversationId]
      if (!conversation) {
        return current
      }

      const messages = [...conversation.messages]
      const lastMessage = messages.at(-1)
      if (lastMessage?.isDraft) {
        messages[messages.length - 1] = nextMessage
      } else {
        messages.push(nextMessage)
      }

      return {
        ...current,
        [conversationId]: {
          ...conversation,
          title: summary.title,
          updated_at: summary.updated_at,
          model: summary.model,
          messages,
        },
      }
    })

    updateConversationSummary(summary)
  }

  const readSseStream = async (response, conversationId) => {
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let currentEvent = 'message'

    while (true) {
      const { value, done } = await reader.read()
      if (done) {
        break
      }

      buffer += decoder.decode(value, { stream: true })
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() ?? ''

      for (const chunk of chunks) {
        if (!chunk.trim()) {
          continue
        }

        const lines = chunk.split('\n')
        let payload = ''
        for (const line of lines) {
          if (line.startsWith('event:')) {
            currentEvent = line.replace('event:', '').trim()
          }
          if (line.startsWith('data:')) {
            payload += line.replace('data:', '').trim()
          }
        }

        if (!payload) {
          continue
        }

        const data = JSON.parse(payload)
        if (currentEvent === 'chunk') {
          updateDraftMessage(conversationId, (message) => ({
            ...message,
            content: `${message.content}${data.delta}`,
            parts: [{ type: 'text', content: `${message.content}${data.delta}` }, ...(message.parts.filter((part) => part.type === 'tool'))],
          }))
        }

        if (currentEvent === 'tool_call') {
          updateDraftMessage(conversationId, (message) => ({
            ...message,
            parts: [
              { type: 'text', content: message.content },
              ...message.parts.filter((part) => part.type === 'tool'),
              data,
            ].filter((part) => part.type !== 'text' || part.content),
          }))
        }

        if (currentEvent === 'tool_result') {
          updateDraftMessage(conversationId, (message) => ({
            ...message,
            parts: message.parts.map((part) =>
              part.type === 'tool' && part.tool_id === data.tool_id ? data : part,
            ),
          }))
        }

        if (currentEvent === 'done') {
          replaceDraftMessage(conversationId, data.message, data.conversation)
        }

        if (currentEvent === 'error') {
          throw new Error(data.message || '生成回复失败')
        }
      }
    }
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!input.trim() || sending) {
      return
    }

    setSending(true)
    setError('')
    const prompt = input.trim()
    let conversationId = activeConversationId
    setInput('')

    try {
      conversationId ??= await createConversation()
      const userMessage = {
        id: `user-${crypto.randomUUID()}`,
        role: 'user',
        content: prompt,
        timestamp: new Date().toISOString(),
        parts: [{ type: 'text', content: prompt }],
      }

      setMessagesByConversation((current) => {
        const baseConversation = current[conversationId] ?? {
          id: conversationId,
          title: '新对话',
          model: selectedModel,
          messages: [],
        }

        return {
          ...current,
          [conversationId]: {
            ...baseConversation,
            model: selectedModel,
            messages: [...baseConversation.messages, userMessage, createDraftAssistant()],
          },
        }
      })

      const response = await fetch(`/api/conversations/${conversationId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: prompt, model: selectedModel }),
      })

      if (!response.ok || !response.body) {
        throw new Error('发送消息失败')
      }

      await readSseStream(response, conversationId)
    } catch (submitError) {
      setError(submitError.message)
      updateDraftMessage(conversationId, (message) => ({
        ...message,
        isDraft: false,
        content: '暂时无法生成回复，请稍后再试。',
        parts: [{ type: 'text', content: '暂时无法生成回复，请稍后再试。' }],
      }))
    } finally {
      setSending(false)
    }
  }

  const handleFeedback = async (messageId, feedback) => {
    if (!activeConversationId) {
      return
    }

    setMessagesByConversation((current) => ({
      ...current,
      [activeConversationId]: {
        ...current[activeConversationId],
        messages: current[activeConversationId].messages.map((message) =>
          message.id === messageId ? { ...message, feedback } : message,
        ),
      },
    }))

    await fetch(`/api/conversations/${activeConversationId}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message_id: messageId, feedback }),
    })
  }

  if (loading) {
    return <div className="loading-screen">正在加载福大灵犀…</div>
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-card">
          <img src="/assets/FZU.png" alt="福州大学" className="brand-logo" />
          <div>
            <h1>福大灵犀</h1>
            <p>React + LangGraph</p>
          </div>
        </div>

        <button className="primary-button" onClick={handleNewConversation} type="button">
          + 新建对话
        </button>

        <label className="field-label" htmlFor="model-select">
          对话模型
        </label>
        <select
          id="model-select"
          className="model-select"
          value={selectedModel}
          onChange={(event) => setSelectedModel(event.target.value)}
        >
          {models.map((model) => (
            <option key={model.id} value={model.id}>
              {model.label}
            </option>
          ))}
        </select>

        <div className="sidebar-section">
          <div className="sidebar-section-title">已保存对话</div>
          <div className="conversation-list">
            {conversations.length === 0 ? (
              <div className="empty-sidebar">还没有历史对话，开始新的提问吧。</div>
            ) : (
              conversations.map((conversation) => (
                <button
                  key={conversation.id}
                  type="button"
                  className={`conversation-card ${
                    conversation.id === activeConversationId ? 'conversation-card--active' : ''
                  }`}
                  onClick={() => setActiveConversationId(conversation.id)}
                >
                  <div className="conversation-card-content">
                    <strong>{conversation.title}</strong>
                    <span>{conversation.preview || '等待你的第一条消息…'}</span>
                  </div>
                  <span
                    className="conversation-delete"
                    onClick={(event) => {
                      event.stopPropagation()
                      void handleDeleteConversation(conversation.id)
                    }}
                  >
                    ×
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      </aside>

      <main className="chat-layout">
        <header className="chat-header">
          <div>
            <h2>{activeConversation?.title ?? '新的对话'}</h2>
            <p>围绕福州大学知识库与联网搜索的智能问答</p>
          </div>
          <div className="chat-header-badge">{models.find((model) => model.id === selectedModel)?.label ?? selectedModel}</div>
        </header>

        <section className="message-list">
          {activeMessages.length === 0 ? (
            <div className="empty-state">
              <img src="/assets/FZU.png" alt="福大灵犀" className="empty-state-logo" />
              <h3>像 ChatGPT 一样开始一次新对话</h3>
              <p>{EMPTY_ASSISTANT_MESSAGE}</p>
            </div>
          ) : (
            activeMessages.map((message) => (
              <article
                key={message.id}
                className={`message-row ${message.role === 'user' ? 'message-row--user' : ''}`}
              >
                <div className={`avatar ${message.role === 'user' ? 'avatar--user' : 'avatar--assistant'}`}>
                  {message.role === 'user' ? 'U' : <img src="/assets/FZU.png" alt="assistant" />}
                </div>
                <div className="message-body">
                  <div className="message-meta">
                    <span>{message.role === 'user' ? '你' : '福大灵犀'}</span>
                    <time>{formatTime(message.timestamp)}</time>
                  </div>
                  <div className="message-bubble">
                    {message.parts
                      .filter((part) => part.type === 'text' && part.content)
                      .map((part, index) => (
                        <p key={`${message.id}-text-${index}`}>{part.content}</p>
                      ))}
                    {message.parts
                      .filter((part) => part.type === 'tool')
                      .map((part) => (
                        <div key={part.tool_id} className="tool-card">
                          <div className="tool-card-title">{part.status_label}</div>
                          <div className="tool-card-query">{part.query}</div>
                          {part.urls?.length > 0 && (
                            <div className="tool-links">
                              {part.urls.map((url) => (
                                <a key={url} href={url} target="_blank" rel="noreferrer">
                                  {url}
                                </a>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                  </div>
                  {message.role === 'assistant' && !message.isDraft && (
                    <div className="feedback-row">
                      <button
                        type="button"
                        className={message.feedback === 'up' ? 'feedback-button feedback-button--active' : 'feedback-button'}
                        onClick={() => void handleFeedback(message.id, 'up')}
                      >
                        👍
                      </button>
                      <button
                        type="button"
                        className={message.feedback === 'down' ? 'feedback-button feedback-button--active' : 'feedback-button'}
                        onClick={() => void handleFeedback(message.id, 'down')}
                      >
                        👎
                      </button>
                    </div>
                  )}
                </div>
              </article>
            ))
          )}
          <div ref={messagesEndRef} />
        </section>

        <footer className="composer-shell">
          {error ? <div className="error-banner">{error}</div> : null}
          <form className="composer" onSubmit={handleSubmit}>
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="输入福州大学相关问题，按 Enter 发送，Shift + Enter 换行"
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  void handleSubmit(event)
                }
              }}
            />
            <button className="send-button" type="submit" disabled={sending || !input.trim()}>
              {sending ? '发送中…' : '发送'}
            </button>
          </form>
        </footer>
      </main>
    </div>
  )
}

export default App
