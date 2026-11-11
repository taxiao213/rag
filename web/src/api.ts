/* API 客户端：API Key 存储在 localStorage，随请求带 X-API-Key 头 */

export type DocItem = {
  document_id: string
  filename: string
  file_type: string
  modality: string
  status: string
  importance: string
  size_bytes: number
  version: number
  created_at: string
}

export type RefItem = {
  ref_id: number
  chunk_id: string
  filename: string
  file_type: string
  modality: string
  page_no: number | null
  slide_no: number | null
  start_ts: number | null
  end_ts: number | null
  asset_id: string | null
}

export type ChunkDetail = {
  chunk_id: string
  content: string
  modality: string
  page_no: number | null
  slide_no: number | null
  start_ts: number | null
  end_ts: number | null
  asset: {
    asset_id: string
    asset_type: string
    url: string
    width: number | null
    height: number | null
    timestamp: number | null
  } | null
  document: {
    document_id: string | null
    filename: string
    file_type: string
    file_url: string | null
  }
}

export type WatchPath = {
  path: string
  importance: 'normal' | 'high'
  enabled: boolean
  exists?: boolean
}

export type ScanStats = {
  added: number
  updated: number
  deleted: number
  skipped: number
  errors: string[]
}

export type ChatSettings = {
  base_url: string
  api_key_masked: string
  api_key_configured: boolean
  llm_model: string
  max_tokens: number
}

export type IndexSettings = {
  base_url: string
  api_key_masked: string
  api_key_configured: boolean
  embedding_model: string
  rerank_model: string
  vlm_model: string
}

export type LLMSettings = {
  chat: ChatSettings
  index: IndexSettings
}

const KEY_STORAGE = 'kb-rag-api-key'

export function getApiKey(): string {
  return localStorage.getItem(KEY_STORAGE) ?? ''
}
export function setApiKey(key: string): void {
  localStorage.setItem(KEY_STORAGE, key)
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const resp = await fetch(path, {
    ...init,
    headers: {
      'X-API-Key': getApiKey(),
      ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init.headers,
    },
  })
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(body.detail ?? `HTTP ${resp.status}`)
  }
  return resp
}

export const api = {
  getChunk: async (id: string): Promise<ChunkDetail> =>
    (await request(`/api/chunks/${id}`)).json(),

  listConversations: async (): Promise<{ id: string; title: string; updated_at: string }[]> =>
    (await request('/api/conversations')).json(),

  getConversation: async (
    id: string,
  ): Promise<{ id: string; title: string; messages: { role: string; content: string; refs: RefItem[] }[] }> =>
    (await request(`/api/conversations/${id}`)).json(),

  deleteConversation: async (id: string): Promise<unknown> =>
    (await request(`/api/conversations/${id}`, { method: 'DELETE' })).json(),

  listDocuments: async (): Promise<DocItem[]> =>
    (await request('/api/documents')).json(),

  upload: async (file: File, importance: string): Promise<unknown> => {
    const fd = new FormData()
    fd.append('file', file)
    return (
      await request(`/api/documents?importance=${importance}`, { method: 'POST', body: fd })
    ).json()
  },

  deleteDocument: async (id: string): Promise<unknown> =>
    (await request(`/api/documents/${id}`, { method: 'DELETE' })).json(),

  reindex: async (id: string): Promise<unknown> =>
    (await request(`/api/documents/${id}/reindex`, { method: 'POST' })).json(),

  getPaths: async (): Promise<{ paths: WatchPath[] }> =>
    (await request('/api/paths')).json(),

  savePaths: async (paths: WatchPath[]): Promise<unknown> =>
    (await request('/api/paths', { method: 'PUT', body: JSON.stringify({ paths }) })).json(),

  scanPaths: async (): Promise<ScanStats> =>
    (await request('/api/paths/scan', { method: 'POST' })).json(),

  browsePath: async (): Promise<{ path: string | null; cancelled: boolean }> =>
    (await request('/api/paths/browse', { method: 'POST' })).json(),

  getLLMSettings: async (): Promise<LLMSettings> =>
    (await request('/api/settings/llm')).json(),

  saveLLMSettings: async (body: Record<string, unknown>): Promise<unknown> =>
    (await request('/api/settings/llm', { method: 'PUT', body: JSON.stringify(body) })).json(),

  testLLMSettings: async (body: Record<string, unknown>): Promise<{ ok: boolean; message: string }> =>
    (await request('/api/settings/llm/test', { method: 'POST', body: JSON.stringify(body) })).json(),

  /** SSE 流式问答：逐 token 回调，结束回调 refs，开始回调 conversation id */
  queryStream: async (
    query: string,
    onToken: (t: string) => void,
    onRefs: (refs: RefItem[]) => void,
    conversationId?: string | null,
    onConversation?: (id: string) => void,
  ): Promise<void> => {
    const resp = await fetch('/api/query', {
      method: 'POST',
      headers: { 'X-API-Key': getApiKey(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, conversation_id: conversationId ?? null }),
    })
    if (!resp.ok || !resp.body) {
      const body = await resp.json().catch(() => ({ detail: resp.statusText }))
      throw new Error(body.detail ?? `HTTP ${resp.status}`)
    }
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // SSE 事件分隔：兼容 \r\n\r\n 与 \n\n
      const events = buffer.split(/\r?\n\r?\n/)
      buffer = events.pop() ?? ''
      for (const ev of events) {
        const line = ev.replace(/\r/g, '').trim()
        if (!line.startsWith('data:')) continue
        const data = line.slice(5).trim()
        if (data === '[DONE]') return
        try {
          const parsed = JSON.parse(data)
          if (parsed.type === 'token') onToken(parsed.content)
          else if (parsed.type === 'refs') onRefs(parsed.refs)
          else if (parsed.type === 'conversation') onConversation?.(parsed.id)
          else if (parsed.type === 'error') throw new Error(parsed.content)
        } catch (err) {
          // error 事件直接向上抛，其余忽略不完整事件
          if (err instanceof Error && err.message) throw err
        }
      }
    }
  },
}
