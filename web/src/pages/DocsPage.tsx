import { useCallback, useEffect, useRef, useState } from 'react'
import { api, DocItem, ScanStats, WatchPath } from '../api'

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

  // 目录同步
  const [paths, setPaths] = useState<WatchPath[]>([])
  const [newPath, setNewPath] = useState('')
  const [newImportance, setNewImportance] = useState<'normal' | 'high'>('normal')
  const [scanning, setScanning] = useState(false)
  const [scanResult, setScanResult] = useState<ScanStats | null>(null)
  const [pathError, setPathError] = useState('')

  const loadPaths = useCallback(() => {
    api.getPaths().then((r) => setPaths(r.paths)).catch(() => {})
  }, [])

  useEffect(() => {
    loadPaths()
  }, [loadPaths])

  const persistPaths = async (next: WatchPath[]) => {
    setPaths(next)
    setPathError('')
    try {
      await api.savePaths(next)
      loadPaths()
    } catch (e) {
      setPathError(e instanceof Error ? e.message : String(e))
    }
  }

  const addPath = async () => {
    const p = newPath.trim()
    if (!p.startsWith('/')) {
      setPathError('请输入绝对路径，如 /data/kb')
      return
    }
    if (paths.some((x) => x.path === p)) {
      setPathError('该路径已存在')
      return
    }
    await persistPaths([...paths, { path: p, importance: newImportance, enabled: true }])
    setNewPath('')
  }

  const runScan = async () => {
    setScanning(true)
    setScanResult(null)
    setPathError('')
    try {
      const stats = await api.scanPaths()
      setScanResult(stats)
      refresh()
    } catch (e) {
      setPathError(e instanceof Error ? e.message : String(e))
    } finally {
      setScanning(false)
    }
  }

  const refresh = useCallback(async () => {
    try {
      setDocs(await api.listDocuments())
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  // 页面打开期间持续轮询：有进行中任务 3s 一次，空闲 15s 一次
  useEffect(() => {
    refresh()
    const hasActive = docs.some((d) => ['indexing', 'pending', 'uploaded'].includes(d.status))
    const t = setInterval(refresh, hasActive ? 3000 : 15000)
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

      <div className="card sync-card">
        <div className="sync-head">
          <div>
            <div className="sync-title">目录同步</div>
            <div className="sync-sub">
              监视服务器上的目录：新文件自动入库、修改自动重建、移除自动清理。每 5 分钟定时扫描，也可手动触发。
            </div>
          </div>
          <button className="btn small" onClick={runScan} disabled={scanning || paths.length === 0}>
            {scanning ? '同步中…' : '立即同步'}
          </button>
        </div>

        {pathError && <div className="test-result fail">{pathError}</div>}
        {scanResult && (
          <div className={`test-result ${scanResult.errors.length ? 'fail' : 'ok'}`}>
            新增 {scanResult.added} · 更新 {scanResult.updated} · 删除 {scanResult.deleted} · 跳过 {scanResult.skipped}
            {scanResult.errors.length > 0 && ` · 错误：${scanResult.errors.join('；')}`}
          </div>
        )}

        {paths.length > 0 && (
          <div className="path-list">
            {paths.map((p) => (
              <div key={p.path} className={`path-row ${p.enabled ? '' : 'disabled'}`}>
                <span className={`dot ${p.exists ? 'ok' : 'err'}`} title={p.exists ? '路径可访问' : '路径不可访问'} />
                <span className="path-name mono">{p.path}</span>
                <span className={`badge ${p.importance === 'high' ? 'warn' : ''}`}>
                  {p.importance === 'high' ? '重要' : '普通'}
                </span>
                <button
                  className="preset-chip"
                  title={p.enabled ? '点击停用' : '点击启用'}
                  onClick={() =>
                    persistPaths(paths.map((x) => (x.path === p.path ? { ...x, enabled: !x.enabled } : x)))
                  }
                >
                  {p.enabled ? '已启用' : '已停用'}
                </button>
                <button
                  className="conv-del"
                  style={{ opacity: 1 }}
                  title="移除路径"
                  onClick={() => persistPaths(paths.filter((x) => x.path !== p.path))}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="path-add">
          <input
            placeholder="输入绝对路径，如 /Users/you/kb 或 /data/docs"
            value={newPath}
            onChange={(e) => setNewPath(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addPath()}
          />
          <button
            className={`preset-chip ${newImportance === 'normal' ? 'active' : ''}`}
            onClick={() => setNewImportance('normal')}
          >
            普通
          </button>
          <button
            className={`preset-chip ${newImportance === 'high' ? 'active' : ''}`}
            onClick={() => setNewImportance('high')}
          >
            重要
          </button>
          <button className="btn small" onClick={addPath} disabled={!newPath.trim()}>
            添加路径
          </button>
        </div>
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
                        if (confirm(`删除《${d.filename}》及其全部索引？\n（仅删除知识库内容，源文件不受影响）`)) {
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
