import { useState } from 'react'
import ChatPage from './pages/ChatPage'
import DocsPage from './pages/DocsPage'
import SettingsPage from './pages/SettingsPage'

type Page = 'chat' | 'docs' | 'settings'

export default function App() {
  const [page, setPage] = useState<Page>('chat')

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="logo">
          <div className="logo-mark">K</div>
          <span>kb-rag</span>
        </div>
        <nav className="nav">
          {(
            [
              ['chat', '对话'],
              ['docs', '文档'],
              ['settings', '设置'],
            ] as [Page, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              className={`nav-item ${page === key ? 'active' : ''}`}
              onClick={() => setPage(key)}
            >
              {label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">多模态知识库 RAG</div>
      </aside>
      <main className="main">
        {page === 'chat' && <ChatPage />}
        {page === 'docs' && <DocsPage />}
        {page === 'settings' && <SettingsPage />}
      </main>
    </div>
  )
}
