import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { KIND, POLICY, STATUS, Tag, VALIDITY, fmtSize, opt } from '../labels.js'

const META_FIELDS = [
  ['doc_id', '文档 ID'],
  ['doc_version_id', '版本 ID'],
  ['knowledge_space_id', '知识空间', true],
  ['knowledge_type', '知识类型', true],
  ['source_type', '来源类型', true],
  ['access_level', '权限级别', true],
  ['processing_policy', '处理位置策略'],
  ['business_domain', '业务域', true],
  ['platform', '平台', true],
  ['market', '目标市场', true],
  ['language', '语言', true],
  ['quality_grade', '质量等级', true],
  ['risk_level', '风险等级', true],
  ['effective_from', '生效日期'],
  ['expires_at', '失效日期'],
]

function ChunkCard({ c, children }) {
  return (
    <div className={`chunk ${c.kind}`}>
      <div className="chunk-head">
        <Tag cls={c.kind === 'parent' ? 'purple' : c.kind === 'child' ? 'blue' : 'gray'}>{KIND[c.kind]}</Tag>
        <code>{c.chunk_id}</code>
        <span>约 {c.tokens} token</span>
        <span className="loc">{c.locator || '—'}</span>
        {c.kind !== 'parent' && <span className={c.embedded ? 'ok' : 'warn'}>{c.embedded ? '已向量化' : '未向量化'}</span>}
      </div>
      <pre>{c.text}</pre>
      {children}
    </div>
  )
}

export default function DocDetail({ id, meta, onBack }) {
  const [doc, setDoc] = useState(null)
  const [view, setView] = useState('chunks')
  const [error, setError] = useState('')

  useEffect(() => {
    api.doc(id).then(setDoc).catch((e) => setError(e.message))
  }, [id])

  if (error) return <div className="alert red">{error}</div>
  if (!doc) return <div className="boot">加载中…</div>

  const children = (pid) => doc.chunks.filter((c) => c.parent_chunk_id === pid)
  const top = doc.chunks.filter((c) => !c.parent_chunk_id)
  const leaf = doc.chunks.filter((c) => c.kind !== 'parent')
  const strategy = meta.strategies[doc.knowledge_type]

  return (
    <>
      <header className="page-head">
        <button className="back" onClick={onBack}>
          ← 返回文档列表
        </button>
        <h1>
          {doc.name} <small>v{doc.version}</small>
        </h1>
        <p>
          <Tag cls={STATUS[doc.status].cls}>{STATUS[doc.status].text}</Tag>{' '}
          <Tag cls={VALIDITY[doc.validity_status].cls}>{VALIDITY[doc.validity_status].text}</Tag> {fmtSize(doc.size)} · 检索块{' '}
          {leaf.length} 个 · 父块 {doc.chunks.length - leaf.length} 个 · {strategy.strategy}（{strategy.size}）
        </p>
        {doc.error && <div className="alert red">{doc.error}</div>}
      </header>
      <div className="detail-grid">
        <section className="card">
          <h2>元数据</h2>
          <dl className="meta-list">
            {META_FIELDS.map(([k, label, isOpt]) => (
              <div key={k}>
                <dt>
                  {label}
                  <code>{k}</code>
                </dt>
                <dd>{isOpt ? opt(meta, k, doc[k]) : k === 'processing_policy' ? POLICY[doc[k]] : doc[k] || '—'}</dd>
              </div>
            ))}
          </dl>
          <h2>处理记录</h2>
          <ul className="log">
            {doc.steps.map((s) => (
              <li key={s.name} className={s.ok ? 'ok' : 'warn'}>
                <b>{s.name}</b> {s.detail} <em>{s.ms} ms</em>
              </li>
            ))}
          </ul>
        </section>
        <section className="card">
          <div className="card-head">
            <div className="seg">
              <button className={view === 'chunks' ? 'active' : ''} onClick={() => setView('chunks')}>
                切块结果
              </button>
              <button className={view === 'parsed' ? 'active' : ''} onClick={() => setView('parsed')}>
                解析结果（Markdown）
              </button>
            </div>
          </div>
          {view === 'parsed' ? (
            <pre className="parsed">{doc.parsed_md}</pre>
          ) : (
            <div className="chunks">
              {top.map((c) =>
                c.kind === 'parent' ? (
                  <ChunkCard key={c.chunk_id} c={c}>
                    <div className="children">
                      {children(c.chunk_id).map((cc) => (
                        <ChunkCard key={cc.chunk_id} c={cc} />
                      ))}
                    </div>
                  </ChunkCard>
                ) : (
                  <ChunkCard key={c.chunk_id} c={c} />
                ),
              )}
            </div>
          )}
        </section>
      </div>
    </>
  )
}
