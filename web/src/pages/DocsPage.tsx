import { useCallback, useEffect, useRef, useState } from 'react'
import { api, DocItem } from '../api'

const STATUS_LABEL: Record<string, string> = {
  indexed: '已索引',
  indexing: '索引中',
  pending: '排队中',
  uploaded: '已上传',
  failed: '失败',
}

function fmtSize(bytes: number): string {
  if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024).toFixed(0)} KB`
}

export default function DocsPage() {
  const [docs, setDocs] = useState<DocItem[]>([])
  const [importance, setImportance] = useState<'normal' | 'high'>('normal')
  const [over, setOver] = useState(false)
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    try {
      setDocs(await api.listDocuments())
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  // 有进行中任务时 3s 轮询
  useEffect(() => {
    refresh()
    const hasActive = docs.some((d) => ['indexing', 'pending', 'uploaded'].includes(d.status))
    if (!hasActive) return
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [docs, refresh])

  const uploadFiles = async (files: FileList | null) => {
    if (!files?.length) return
    setUploading(true)
    try {
      for (const f of Array.from(files)) await api.upload(f, importance)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setUploading(false)
    }
  }

  return (
    <div>
      <h1 className="page-title">文档</h1>
      <p className="page-sub">
        上传后自动解析入库。重要文件秒级索引；普通文件 ≤10 分钟定时入库。
      </p>

      {error && <div className="test-result fail" style={{ marginBottom: 16 }}>{error}</div>}

      <div
        className={`dropzone ${over ? 'over' : ''}`}
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); uploadFiles(e.dataTransfer.files) }}
      >
        <div style={{ fontSize: 15, marginBottom: 8 }}>
          {uploading ? '上传中…' : '拖拽文件到此处，或点击选择'}
        </div>
        <div style={{ fontSize: 'var(--text-sm)' }}>
          支持 pdf / docx / xlsx / pptx / txt / md / 图片 · 单文件 ≤ 500MB
        </div>
        <div style={{ marginTop: 12, display: 'flex', gap: 8, justifyContent: 'center' }}
             onClick={(e) => e.stopPropagation()}>
          <button
            className={`preset-chip ${importance === 'normal' ? 'active' : ''}`}
            onClick={() => setImportance('normal')}
          >
            普通（定时入库）
          </button>
          <button
            className={`preset-chip ${importance === 'high' ? 'active' : ''}`}
            onClick={() => setImportance('high')}
          >
            重要（立即索引）
          </button>
        </div>
        <input
          ref={fileRef}
          type="file"
          multiple
          style={{ display: 'none' }}
          onChange={(e) => uploadFiles(e.target.files)}
        />
      </div>

      {docs.length === 0 ? (
        <div className="empty-hint">知识库为空，上传第一个文档开始。</div>
      ) : (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <table className="doc-table">
            <thead>
              <tr>
                <th>名称</th><th>类型</th><th>大小</th><th>状态</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.document_id}>
                  <td className="name">{d.filename}</td>
                  <td className="mono" style={{ fontSize: 12 }}>{d.file_type} · {d.modality}</td>
                  <td className="mono" style={{ fontSize: 12 }}>{fmtSize(d.size_bytes)}</td>
                  <td>
                    <span className={`status-badge ${d.status}`}>
                      <span className="dot" />
                      {STATUS_LABEL[d.status] ?? d.status}
                    </span>
                  </td>
                  <td style={{ display: 'flex', gap: 6 }}>
                    {d.status === 'failed' && (
                      <button className="btn small" onClick={() => api.reindex(d.document_id).then(refresh)}>
                        重试
                      </button>
                    )}
                    <button
                      className="btn small danger"
                      onClick={async () => {
                        if (confirm(`删除《${d.filename}》及其全部索引？`)) {
                          await api.deleteDocument(d.document_id)
                          refresh()
                        }
                      }}
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
