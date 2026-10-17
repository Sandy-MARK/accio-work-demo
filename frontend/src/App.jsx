import { useEffect, useState } from 'react'
import { api } from './api.js'
import DocList from './pages/DocList.jsx'
import DocDetail from './pages/DocDetail.jsx'
import SearchTest from './pages/SearchTest.jsx'
import Crawl from './pages/Crawl.jsx'

const TABS = [
  { key: 'docs', label: '文档管理' },
  { key: 'crawl', label: '网页抓取' },
  { key: 'search', label: '检索测试' },
]

export default function App() {
  const [meta, setMeta] = useState(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState('docs')
  const [detailId, setDetailId] = useState(null)

  useEffect(() => {
    api.meta().then(setMeta).catch((e) => setError(`无法连接后端：${e.message}`))
  }, [])

  if (error) return <div className="boot-error">{error}</div>
  if (!meta) return <div className="boot">加载中…</div>

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          Accio Work
          <span>知识库后台</span>
        </div>
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`nav ${tab === t.key && !detailId ? 'active' : ''}`}
            onClick={() => {
              setTab(t.key)
              setDetailId(null)
            }}
          >
            {t.label}
          </button>
        ))}
        <div className="model-card">
          <div>向量模型：{meta.models.embedding}（{meta.models.dimensions} 维）</div>
          <div>重排模型：{meta.models.rerank}</div>
          <div>
            召回 {meta.retrieval.recall_k} → 阈值 {meta.retrieval.threshold} → Top-{meta.retrieval.top_k}
          </div>
          <div>
            问答直答 ≥{meta.retrieval.qa_direct}，候选 ≥{meta.retrieval.qa_suggest}
          </div>
          <div className={meta.api_key_configured ? 'ok' : 'warn'}>
            {meta.api_key_configured ? '百炼 API Key 已配置' : '未配置百炼 API Key，向量化与检索不可用'}
          </div>
        </div>
      </aside>
      <main className="main">
        {detailId ? (
          <DocDetail id={detailId} meta={meta} onBack={() => setDetailId(null)} />
        ) : tab === 'docs' ? (
          <DocList meta={meta} onOpen={setDetailId} />
        ) : tab === 'crawl' ? (
          <Crawl meta={meta} />
        ) : (
          <SearchTest meta={meta} />
        )}
      </main>
    </div>
  )
}
