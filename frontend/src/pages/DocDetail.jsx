import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { KIND, POLICY, REVIEW, ROW_STATUS, STATUS, Tag, VALIDITY, fmtSize, opt } from '../labels.js'

const META_FIELDS = [
  ['doc_id', '文档 ID'],
  ['doc_version_id', '版本 ID'],
  ['knowledge_space_id', '知识空间', true],
  ['knowledge_type', '知识类型', true],
  ['table_kind', '表格类别', true],
  ['source_type', '来源类型', true],
  ['source_url', '来源网址'],
  ['access_level', '权限级别', true],
  ['dept_ids', '可见部门', true],
  ['review_status', '审核状态', true],
  ['pii_level', '个人信息等级', true],
  ['processing_policy', '处理位置策略'],
  ['business_domain', '业务域', true],
  ['platform', '平台', true],
  ['market', '目标市场', true],
  ['language', '语言', true],
  ['quality_grade', '质量等级', true],
  ['risk_level', '风险等级', true],
  ['effective_from', '生效日期'],
  ['expires_at', '失效日期'],
  ['content_hash', '内容哈希'],
]

function value(meta, doc, k, isOpt) {
  if (isOpt) return opt(meta, k, doc[k])
  if (k === 'processing_policy') return POLICY[doc[k]]
  if (k === 'content_hash') return doc[k] ? doc[k].slice(0, 12) + '…' : '—'
  return doc[k] || '—'
}

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

function RowsTable({ meta, doc }) {
  const fields = meta.table_fields[doc.table_kind]
  const extras = [...new Set(doc.table_rows.flatMap((r) => Object.keys(r.data.extra)))]
  return (
    <div className="table-wrap">
      <table className="table compact">
        <thead>
          <tr>
            <th>位置</th>
            {fields.map(([k, l]) => (
              <th key={k}>
                {l}
                <code>{k}</code>
              </th>
            ))}
            {extras.map((e) => (
              <th key={e}>
                {e}
                <code>附加字段</code>
              </th>
            ))}
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {doc.table_rows.map((r) => (
            <tr key={r.sheet + r.row_no} className={r.row_status !== 'active' ? 'muted' : ''}>
              <td className="sub">
                {r.sheet} 第 {r.row_no} 行
              </td>
              {fields.map(([k]) => (
                <td key={k}>{r.data.fields[k] ?? ''}</td>
              ))}
              {extras.map((e) => (
                <td key={e}>{r.data.extra[e] ?? ''}</td>
              ))}
              <td>
                <Tag cls={ROW_STATUS[r.row_status].cls}>{ROW_STATUS[r.row_status].text}</Tag>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function QaList({ units }) {
  return (
    <div className="chunks">
      {units.map((u) => (
        <div key={u.qa_id} className="chunk">
          <div className="chunk-head">
            <code>{u.qa_id}</code>
            <span className="loc">{u.locator || '—'}</span>
            <span className={u.embedded ? 'ok' : 'warn'}>{u.embedded ? `已向量化 ${1 + u.similar_questions.length} 条问法` : '未向量化'}</span>
          </div>
          <div className="qa-q">
            <Tag cls="blue">标准问</Tag> {u.standard_question}
          </div>
          {u.similar_questions.length > 0 && (
            <div className="qa-sims">
              <Tag cls="gray">相似问</Tag>
              {u.similar_questions.map((s) => (
                <span key={s}>{s}</span>
              ))}
            </div>
          )}
          <pre className="qa-a">{u.answer}</pre>
        </div>
      ))}
    </div>
  )
}

export default function DocDetail({ id, meta, onBack }) {
  const [doc, setDoc] = useState(null)
  const [view, setView] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .doc(id)
      .then((d) => {
        setDoc(d)
        setView(d.table_rows.length && !d.chunks.length ? 'rows' : d.qa_units.length ? 'qa' : 'chunks')
      })
      .catch((e) => setError(e.message))
  }, [id])

  if (error) return <div className="alert red">{error}</div>
  if (!doc) return <div className="boot">加载中…</div>

  const children = (pid) => doc.chunks.filter((c) => c.parent_chunk_id === pid)
  const top = doc.chunks.filter((c) => !c.parent_chunk_id)
  const leaf = doc.chunks.filter((c) => c.kind !== 'parent')
  const strategy = meta.strategies[doc.knowledge_type]
  const views = [
    doc.qa_units.length > 0 && ['qa', `标准问答（${doc.qa_units.length}）`],
    doc.table_rows.length > 0 && ['rows', `结构化数据（${doc.table_rows.length} 行）`],
    doc.chunks.length > 0 && ['chunks', `切块结果（${leaf.length}）`],
    ['parsed', '解析结果（Markdown）'],
  ].filter(Boolean)

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
          <Tag cls={REVIEW[doc.review_status].cls}>{REVIEW[doc.review_status].text}</Tag>{' '}
          <Tag cls={VALIDITY[doc.validity_status].cls}>{VALIDITY[doc.validity_status].text}</Tag> {fmtSize(doc.size)} ·{' '}
          {strategy.strategy}（{strategy.size}）
        </p>
        {doc.error && <div className="alert red">{doc.error}</div>}
      </header>
      <div className="detail-grid">
        <section className="card">
          <h2>元数据</h2>
          <dl className="meta-list">
            {META_FIELDS.filter(([k]) => doc[k] || !['table_kind', 'dept_ids', 'source_url'].includes(k)).map(([k, label, isOpt]) => (
              <div key={k}>
                <dt>
                  {label}
                  <code>{k}</code>
                </dt>
                <dd>{value(meta, doc, k, isOpt)}</dd>
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
              {views.map(([k, l]) => (
                <button key={k} className={view === k ? 'active' : ''} onClick={() => setView(k)}>
                  {l}
                </button>
              ))}
            </div>
          </div>
          {view === 'parsed' && <pre className="parsed">{doc.parsed_md}</pre>}
          {view === 'rows' && <RowsTable meta={meta} doc={doc} />}
          {view === 'qa' && <QaList units={doc.qa_units} />}
          {view === 'chunks' && (
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
