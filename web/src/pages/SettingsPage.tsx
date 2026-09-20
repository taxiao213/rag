import { useEffect, useState } from 'react'
import { api, LLMSettings } from '../api'

const PRESETS = [
  { name: '阿里云百炼', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-max' },
  { name: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  { name: '硅基流动', base_url: 'https://api.siliconflow.cn/v1', model: 'Qwen/Qwen2.5-72B-Instruct' },
  { name: 'OpenAI', base_url: 'https://api.openai.com/v1', model: 'gpt-4o' },
  { name: '自定义', base_url: '', model: '' },
]

const MODEL_OPTIONS: Record<string, string[]> = {
  '阿里云百炼': ['qwen-max', 'qwen-plus', 'qwen-turbo'],
  DeepSeek: ['deepseek-chat', 'deepseek-reasoner'],
  硅基流动: ['Qwen/Qwen2.5-72B-Instruct', 'deepseek-ai/DeepSeek-V3'],
  OpenAI: ['gpt-4o', 'gpt-4o-mini'],
}

export default function SettingsPage() {
  const [form, setForm] = useState<LLMSettings | null>(null)
  const [apiKey, setApiKeyField] = useState('')
  const [preset, setPreset] = useState('阿里云百炼')
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    api
      .getLLMSettings()
      .then(setForm)
      .catch((e) => setLoadError(e instanceof Error ? e.message : String(e)))
  }, [])

  if (loadError)
    return (
      <div>
        <h1 className="page-title">设置</h1>
        <div className="test-result fail">{loadError}（读取设置需要查询级 Key）</div>
      </div>
    )
  if (!form) return <div className="empty-hint">加载中…</div>

  const applyPreset = (name: string) => {
    setPreset(name)
    const p = PRESETS.find((x) => x.name === name)!
    if (p.base_url) setForm({ ...form, base_url: p.base_url, llm_model: p.model || form.llm_model })
  }

  const test = async () => {
    setTesting(true)
    setResult(null)
    try {
      const r = await api.testLLMSettings({
        base_url: form.base_url,
        api_key: apiKey || null,
        llm_model: form.llm_model,
      })
      setResult(r)
    } catch (e) {
      setResult({ ok: false, message: e instanceof Error ? e.message : String(e) })
    } finally {
      setTesting(false)
    }
  }

  const save = async () => {
    setSaving(true)
    try {
      await api.saveLLMSettings({
        base_url: form.base_url,
        api_key: apiKey || null,
        llm_model: form.llm_model,
        embedding_model: form.embedding_model,
        rerank_model: form.rerank_model,
        vlm_model: form.vlm_model,
        max_tokens: form.max_tokens,
      })
      setApiKeyField('')
      setForm(await api.getLLMSettings())
      setResult({ ok: true, message: '已保存，即时生效' })
    } catch (e) {
      setResult({ ok: false, message: e instanceof Error ? e.message : String(e) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <h1 className="page-title">设置</h1>
      <p className="page-sub">配置云端大模型 API，保存即时生效，无需重启。修改需管理级 Key。</p>

      <div className="settings-grid">
        <div className="card">
          <div className="provider-presets">
            {PRESETS.map((p) => (
              <button
                key={p.name}
                className={`preset-chip ${preset === p.name ? 'active' : ''}`}
                onClick={() => applyPreset(p.name)}
              >
                {p.name}
              </button>
            ))}
          </div>

          <div className="field">
            <label>Base URL（OpenAI 兼容协议）</label>
            <input
              className="input mono"
              value={form.base_url}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })}
            />
          </div>

          <div className="field">
            <label>
              API Key
              {form.api_key_configured && (
                <span className="mono" style={{ marginLeft: 8, color: 'var(--color-ok)' }}>
                  已配置 {form.api_key_masked}
                </span>
              )}
            </label>
            <input
              className="input mono"
              type="password"
              placeholder={form.api_key_configured ? '留空保持不变' : 'sk-...'}
              value={apiKey}
              onChange={(e) => setApiKeyField(e.target.value)}
            />
          </div>

          <div className="field">
            <label>生成模型（自由输入，如下拉提示可选）</label>
            <input
              className="input mono"
              list="model-suggestions"
              placeholder="例如 qwen-max / deepseek-chat / gpt-4o"
              value={form.llm_model}
              onChange={(e) => setForm({ ...form, llm_model: e.target.value })}
            />
            <datalist id="model-suggestions">
              {(MODEL_OPTIONS[preset] ?? []).map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </div>

          <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
            <button className="btn" onClick={test} disabled={testing}>
              {testing ? '测试中…' : '测试连接'}
            </button>
            <button className="btn primary" onClick={save} disabled={saving}>
              {saving ? '保存中…' : '保存并生效'}
            </button>
          </div>
          {result && <div className={`test-result ${result.ok ? 'ok' : 'fail'}`}>{result.message}</div>}
        </div>

        <div className="card">
          <h3 style={{ fontFamily: 'var(--font-body)', marginBottom: 12 }}>高级参数</h3>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>最大输出 token</label>
            <input
              className="input"
              type="number"
              value={form.max_tokens}
              onChange={(e) => setForm({ ...form, max_tokens: parseInt(e.target.value) || 2048 })}
            />
          </div>
        </div>

        <div className="card" style={{ borderLeft: '3px solid var(--color-warn)' }}>
          <h3 style={{ fontFamily: 'var(--font-body)', marginBottom: 8 }}>索引模型（改动需谨慎）</h3>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)', marginBottom: 12 }}>
            更换 Embedding 模型后必须全量重建索引，否则新旧向量不可比。
            当前：embedding <span className="mono">{form.embedding_model}</span> ·
            rerank <span className="mono">{form.rerank_model}</span> ·
            vlm <span className="mono">{form.vlm_model}</span>
          </p>
        </div>
      </div>
    </div>
  )
}
