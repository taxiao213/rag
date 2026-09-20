import { useEffect, useState } from 'react'
import { api, LLMSettings } from '../api'

const PRESETS = [
  { name: '阿里云百炼', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-max', embedding: 'text-embedding-v3' },
  { name: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat', embedding: '' },
  { name: '硅基流动', base_url: 'https://api.siliconflow.cn/v1', model: 'Qwen/Qwen2.5-72B-Instruct', embedding: 'BAAI/bge-m3' },
  { name: 'OpenAI', base_url: 'https://api.openai.com/v1', model: 'gpt-4o', embedding: 'text-embedding-3-large' },
  { name: '自定义', base_url: '', model: '', embedding: '' },
]

type TestResult = { ok: boolean; message: string } | null

export default function SettingsPage() {
  const [form, setForm] = useState<LLMSettings | null>(null)
  const [chatKey, setChatKey] = useState('')
  const [indexKey, setIndexKey] = useState('')
  const [busy, setBusy] = useState('')
  const [chatResult, setChatResult] = useState<TestResult>(null)
  const [indexResult, setIndexResult] = useState<TestResult>(null)
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    api.getLLMSettings().then(setForm).catch((e) => setLoadError(e instanceof Error ? e.message : String(e)))
  }, [])

  if (loadError)
    return (
      <div>
        <h1 className="page-title">设置</h1>
        <div className="test-result fail">{loadError}</div>
      </div>
    )
  if (!form) return <div className="empty-hint">加载中…</div>

  const applyPreset = (group: 'chat' | 'index', baseUrl: string, model: string) => {
    if (!baseUrl) return
    if (group === 'chat') setForm({ ...form, chat: { ...form.chat, base_url: baseUrl, llm_model: model || form.chat.llm_model } })
    else setForm({ ...form, index: { ...form.index, base_url: baseUrl, embedding_model: model || form.index.embedding_model } })
  }

  const test = async (group: 'chat' | 'index') => {
    setBusy(`test-${group}`)
    const setR = group === 'chat' ? setChatResult : setIndexResult
    setR(null)
    try {
      const body =
        group === 'chat'
          ? { group, base_url: form.chat.base_url, api_key: chatKey || null, llm_model: form.chat.llm_model }
          : { group, base_url: form.index.base_url, api_key: indexKey || null, embedding_model: form.index.embedding_model }
      setR(await api.testLLMSettings(body))
    } catch (e) {
      setR({ ok: false, message: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy('')
    }
  }

  const save = async (group: 'chat' | 'index') => {
    setBusy(`save-${group}`)
    const setR = group === 'chat' ? setChatResult : setIndexResult
    try {
      const body =
        group === 'chat'
          ? { chat: { base_url: form.chat.base_url, api_key: chatKey || null, llm_model: form.chat.llm_model, max_tokens: form.chat.max_tokens } }
          : { index: { base_url: form.index.base_url, api_key: indexKey || null, embedding_model: form.index.embedding_model, rerank_model: form.index.rerank_model, vlm_model: form.index.vlm_model } }
      await api.saveLLMSettings(body)
      if (group === 'chat') setChatKey('')
      else setIndexKey('')
      setForm(await api.getLLMSettings())
      setR({ ok: true, message: '已保存，即时生效' })
    } catch (e) {
      setR({ ok: false, message: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy('')
    }
  }

  return (
    <div>
      <h1 className="page-title">设置</h1>
      <p className="page-sub">生成模型用于对话回答；索引模型用于文档向量化与图片理解，两者可用不同供应商。</p>

      <div className="settings-grid">
        {/* ========== 生成模型 ========== */}
        <div className="card">
          <h3 style={{ fontFamily: 'var(--font-body)', marginBottom: 4 }}>生成模型</h3>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)', marginBottom: 16 }}>
            对话问答使用的大语言模型。
          </p>
          <div className="provider-presets">
            {PRESETS.map((p) => (
              <button key={p.name} className="preset-chip" onClick={() => applyPreset('chat', p.base_url, p.model)}>
                {p.name}
              </button>
            ))}
          </div>
          <div className="field">
            <label>Base URL（OpenAI 兼容协议）</label>
            <input className="input mono" value={form.chat.base_url}
              onChange={(e) => setForm({ ...form, chat: { ...form.chat, base_url: e.target.value } })} />
          </div>
          <div className="field">
            <label>
              API Key
              {form.chat.api_key_configured && (
                <span className="mono" style={{ marginLeft: 8, color: 'var(--color-ok)' }}>已配置 {form.chat.api_key_masked}</span>
              )}
            </label>
            <input className="input mono" type="password"
              placeholder={form.chat.api_key_configured ? '留空保持不变' : 'sk-...'}
              value={chatKey} onChange={(e) => setChatKey(e.target.value)} />
          </div>
          <div className="field">
            <label>模型（自由输入）</label>
            <input className="input mono" placeholder="例如 qwen-max / deepseek-chat / gpt-4o"
              value={form.chat.llm_model}
              onChange={(e) => setForm({ ...form, chat: { ...form.chat, llm_model: e.target.value } })} />
          </div>
          <div className="field">
            <label>最大输出 token</label>
            <input className="input" type="number" value={form.chat.max_tokens}
              onChange={(e) => setForm({ ...form, chat: { ...form.chat, max_tokens: parseInt(e.target.value) || 2048 } })} />
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <button className="btn" onClick={() => test('chat')} disabled={busy === 'test-chat'}>
              {busy === 'test-chat' ? '测试中…' : '测试连接'}
            </button>
            <button className="btn primary" onClick={() => save('chat')} disabled={busy === 'save-chat'}>
              {busy === 'save-chat' ? '保存中…' : '保存并生效'}
            </button>
          </div>
          {chatResult && <div className={`test-result ${chatResult.ok ? 'ok' : 'fail'}`}>{chatResult.message}</div>}
        </div>

        {/* ========== 索引模型 ========== */}
        <div className="card">
          <h3 style={{ fontFamily: 'var(--font-body)', marginBottom: 4 }}>索引模型</h3>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)', marginBottom: 16 }}>
            文档向量化（embedding）、图片理解（VLM）、结果重排（rerank）使用。
            更换 embedding 后需重建全部索引。
          </p>
          <div className="provider-presets">
            {PRESETS.filter((p) => p.embedding || p.name === '自定义').map((p) => (
              <button key={p.name} className="preset-chip" onClick={() => applyPreset('index', p.base_url, p.embedding)}>
                {p.name}
              </button>
            ))}
          </div>
          <div className="field">
            <label>Base URL（OpenAI 兼容协议）</label>
            <input className="input mono" value={form.index.base_url}
              onChange={(e) => setForm({ ...form, index: { ...form.index, base_url: e.target.value } })} />
          </div>
          <div className="field">
            <label>
              API Key
              {form.index.api_key_configured && (
                <span className="mono" style={{ marginLeft: 8, color: 'var(--color-ok)' }}>已配置 {form.index.api_key_masked}</span>
              )}
            </label>
            <input className="input mono" type="password"
              placeholder={form.index.api_key_configured ? '留空保持不变' : 'sk-...'}
              value={indexKey} onChange={(e) => setIndexKey(e.target.value)} />
          </div>
          <div className="field">
            <label>Embedding 模型（自由输入）</label>
            <input className="input mono" placeholder="例如 text-embedding-v3 / text-embedding-3-large"
              value={form.index.embedding_model}
              onChange={(e) => setForm({ ...form, index: { ...form.index, embedding_model: e.target.value } })} />
          </div>
          <div className="field">
            <label>VLM 模型（图片描述，可选）</label>
            <input className="input mono" value={form.index.vlm_model}
              onChange={(e) => setForm({ ...form, index: { ...form.index, vlm_model: e.target.value } })} />
          </div>
          <div className="field">
            <label>Rerank 模型（可选，仅百炼原生接口）</label>
            <input className="input mono" value={form.index.rerank_model}
              onChange={(e) => setForm({ ...form, index: { ...form.index, rerank_model: e.target.value } })} />
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <button className="btn" onClick={() => test('index')} disabled={busy === 'test-index'}>
              {busy === 'test-index' ? '测试中…' : '测试 embedding'}
            </button>
            <button className="btn primary" onClick={() => save('index')} disabled={busy === 'save-index'}>
              {busy === 'save-index' ? '保存中…' : '保存并生效'}
            </button>
          </div>
          {indexResult && <div className={`test-result ${indexResult.ok ? 'ok' : 'fail'}`}>{indexResult.message}</div>}
        </div>
      </div>
    </div>
  )
}
