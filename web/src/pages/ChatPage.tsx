import { useCallback, useEffect, useRef, useState } from 'react'
import { api, RefItem } from '../api'

type Message = {
  role: 'user' | 'assistant'
  content: string
  refs?: RefItem[]
  streaming?: boolean
  error?: string
}

type ConvSummary = { id: string; title: string; updated_at: string }

/** 把回答文本中的 [n] 渲染为可点击引用标记 */
function renderWithCitations(text: string, refs: RefItem[], onJump: (refId: number) => void) {
  const parts = text.split(/(\[\d+\])/g)
  return parts.map((part, i) => {
    const m = part.match(/^\[(\d+)\]$/)
    if (m) {
      const id = parseInt(m[1], 10)
      if (refs.some((r) => r.ref_id === id)) {
        return (
          <button key={i} className="cite-mark" onClick={() => onJump(id)}>
            [{id}]
          </button>
        )
      }
    }
    return <span key={i}>{part}</span>
  })
}

function refLocator(r: RefItem): string {
  if (r.start_ts != null) return `视频 ${r.start_ts.toFixed(0)}s - ${(r.end_ts ?? 0).toFixed(0)}s`
  if (r.page_no) return `第 ${r.page_no} 页`
  if (r.slide_no) return `第 ${r.slide_no} 张幻灯片`
  return ''
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [convs, setConvs] = useState<ConvSummary[]>([])
  const [currentConv, setCurrentConv] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const refreshConvs = useCallback(() => {
    api.listConversations().then(setConvs).catch(() => {})
  }, [])

  useEffect(() => {
    refreshConvs()
  }, [refreshConvs])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const loadConversation = async (id: string) => {
    try {
      const detail = await api.getConversation(id)
      setCurrentConv(id)
      setMessages(
        detail.messages.map((m) => ({
          role: m.role as 'user' | 'assistant',
          content: m.content,
          refs: m.refs,
        })),
      )
    } catch {
      /* 加载失败保持当前状态 */
    }
  }

  const newChat = () => {
    setCurrentConv(null)
    setMessages([])
  }

  const jumpToRef = (refId: number) => {
    document.getElementById(`ref-${refId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    document.getElementById(`ref-${refId}`)?.classList.add('highlight')
    setTimeout(() => document.getElementById(`ref-${refId}`)?.classList.remove('highlight'), 1600)
  }

  const send = async () => {
    const q = input.trim()
    if (!q || busy) return
    setInput('')
    setBusy(true)
    setMessages((m) => [
      ...m,
      { role: 'user', content: q },
      { role: 'assistant', content: '', refs: [], streaming: true },
    ])

    try {
      await api.queryStream(
        q,
        (token) =>
          setMessages((m) => {
            const next = [...m]
            next[next.length - 1] = {
              ...next[next.length - 1],
              content: next[next.length - 1].content + token,
            }
            return next
          }),
        (refs) =>
          setMessages((m) => {
            const next = [...m]
            next[next.length - 1] = { ...next[next.length - 1], refs, streaming: false }
            return next
          }),
        currentConv,
        (id) => {
          if (!currentConv) setCurrentConv(id)
          refreshConvs()
        },
      )
      setMessages((m) => {
        const next = [...m]
        next[next.length - 1] = { ...next[next.length - 1], streaming: false }
        return next
      })
      refreshConvs()
    } catch (e) {
      setMessages((m) => {
        const next = [...m]
        next[next.length - 1] = {
          ...next[next.length - 1],
          streaming: false,
          error: e instanceof Error ? e.message : String(e),
        }
        return next
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="chat-shell">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <h1 className="page-title" style={{ marginBottom: 0 }}>对话</h1>
        <button className="btn small" onClick={newChat}>＋ 新对话</button>
      </div>
      <p className="page-sub">基于知识库内容回答，每个论断标注引用来源。对话记录自动保存。</p>

      {convs.length > 0 && (
        <div className="conv-list">
          {convs.map((c) => (
            <div
              key={c.id}
              className={`conv-item ${currentConv === c.id ? 'active' : ''}`}
              onClick={() => loadConversation(c.id)}
            >
              <span className="conv-title">{c.title}</span>
              <button
                className="conv-del"
                title="删除对话"
                onClick={async (e) => {
                  e.stopPropagation()
                  await api.deleteConversation(c.id)
                  if (currentConv === c.id) newChat()
                  refreshConvs()
                }}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="chat-scroll" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="empty-hint">
            还没有对话。试试问：「知识库里有什么？」
            <br />
            （需先在「文档」页上传并等待索引完成）
          </div>
        )}
        {messages.map((msg, i) =>
          msg.role === 'user' ? (
            <div key={i} className="msg-q">{msg.content}</div>
          ) : (
            <div key={i} className="msg-a">
              {msg.error ? (
                <div className="test-result fail">{msg.error}</div>
              ) : (
                <>
                  {msg.refs && msg.refs.length > 0
                    ? renderWithCitations(msg.content, msg.refs, jumpToRef)
                    : msg.content}
                  {msg.streaming && <span className="cursor" />}
                  {msg.refs && msg.refs.length > 0 && (
                    <div className="refs-row">
                      {msg.refs.map((r) => (
                        <div key={r.ref_id} id={`ref-${r.ref_id}`} className="ref-card">
                          <div className="ref-title">[{r.ref_id}] {r.filename}</div>
                          <div className="ref-meta">
                            {refLocator(r)} · {r.modality}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          ),
        )}
      </div>

      <div className="chat-input-row">
        <input
          placeholder="输入问题，检索你的知识库…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          disabled={busy}
        />
        <button onClick={send} disabled={busy || !input.trim()}>
          {busy ? '生成中…' : '发送'}
        </button>
      </div>
    </div>
  )
}
