import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ChunkDetail, RefItem } from '../api'

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

const MODALITY_LABEL: Record<string, string> = {
  text: '文本',
  image: '图片',
  video_transcript: '视频转录',
  video_frame: '视频帧',
}

type ModalState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'loaded'; chunk: ChunkDetail }

/** 引用溯源弹窗：chunk 全文 / 图片 / 源文件链接 */
function ChunkModal({ state, onClose }: { state: ModalState; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" role="dialog" aria-label="引用原文" onClick={(e) => e.stopPropagation()}>
        {state.kind === 'loading' && (
          <div className="modal-body"><div className="empty-hint">加载中…</div></div>
        )}
        {state.kind === 'error' && (
          <div className="modal-body"><div className="test-result fail">{state.message}</div></div>
        )}
        {state.kind === 'loaded' && (
          <>
            <header className="modal-head">
              <div className="modal-head-text">
                <div className="modal-title">{state.chunk.document.filename}</div>
                <div className="modal-badges">
                  <span className="badge">{MODALITY_LABEL[state.chunk.modality] ?? state.chunk.modality}</span>
                  {state.chunk.page_no != null && <span className="badge">第 {state.chunk.page_no} 页</span>}
                  {state.chunk.slide_no != null && <span className="badge">第 {state.chunk.slide_no} 张幻灯片</span>}
                  {state.chunk.start_ts != null && (
                    <span className="badge">
                      {state.chunk.start_ts.toFixed(0)}s - {(state.chunk.end_ts ?? 0).toFixed(0)}s
                    </span>
                  )}
                </div>
              </div>
              <button className="modal-close" aria-label="关闭" onClick={onClose}>×</button>
            </header>

            <div className="modal-body">
              {state.chunk.asset?.url && (
                <figure className="modal-figure">
                  <img src={state.chunk.asset.url} alt={`${state.chunk.document.filename} 引用图片`} />
                </figure>
              )}
              <div className="modal-section-label">
                {state.chunk.modality === 'image' ? '图片内容描述' : '引用原文'}
              </div>
              <div className="modal-content">{state.chunk.content}</div>
            </div>

            {state.chunk.document.file_url && (
              <footer className="modal-foot">
                <a
                  className="btn small"
                  href={state.chunk.document.file_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  打开源文件 ↗
                </a>
              </footer>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  if (sameDay) return hm
  return `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [convs, setConvs] = useState<ConvSummary[]>([])
  const [currentConv, setCurrentConv] = useState<string | null>(null)
  const [modal, setModal] = useState<ModalState | null>(null)
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

  const openRef = async (chunkId: string) => {
    setModal({ kind: 'loading' })
    try {
      const chunk = await api.getChunk(chunkId)
      setModal({ kind: 'loaded', chunk })
    } catch (e) {
      setModal({ kind: 'error', message: e instanceof Error ? e.message : String(e) })
    }
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
    <div className="chat-layout">
      <aside className="chat-sidebar">
        <button className="btn new-chat-btn" onClick={newChat}>＋ 新对话</button>
        <div className="sidebar-label">历史对话</div>
        <div className="sidebar-list">
          {convs.length === 0 && <div className="sidebar-empty">暂无历史对话</div>}
          {convs.map((c) => (
            <div
              key={c.id}
              className={`sidebar-item ${currentConv === c.id ? 'active' : ''}`}
              onClick={() => loadConversation(c.id)}
            >
              <div className="sidebar-item-text">
                <span className="sidebar-item-title">{c.title}</span>
                <span className="sidebar-item-time">{formatTime(c.updated_at)}</span>
              </div>
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
      </aside>

      <div className="chat-main">
        <h1 className="page-title">对话</h1>
        <p className="page-sub">基于知识库内容回答，每个论断标注引用来源。对话记录自动保存。</p>

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
                          <div
                            key={r.ref_id}
                            id={`ref-${r.ref_id}`}
                            className="ref-card clickable"
                            title="点击查看原文"
                            onClick={() => openRef(r.chunk_id)}
                          >
                            <div className="ref-title">[{r.ref_id}] {r.filename}</div>
                            <div className="ref-meta">
                              {refLocator(r)} · {MODALITY_LABEL[r.modality] ?? r.modality}
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

      {modal && <ChunkModal state={modal} onClose={() => setModal(null)} />}
    </div>
  )
}
