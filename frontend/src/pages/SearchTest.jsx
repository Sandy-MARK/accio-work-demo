import { useState } from 'react'
import { api } from '../api.js'
import { KIND, Tag } from '../labels.js'

const STATUS_TEXT = {
  ok: { text: '命中', cls: 'green' },
  empty: { text: '知识库无依据', cls: 'gray' },
  partial: { text: '未经重排', cls: 'orange' },
}

function Hit({ h, rank, threshold }) {
  const below = h.passed === false
  return (
    <li className={below ? 'below' : ''}>
      <span className="rank">{rank}</span>
      <div>
        <div className="hit-head">
          <b>{h.doc_name}</b> <small>v{h.version}</small> <Tag cls="gray">{KIND[h.kind]}</Tag>
          <span className="loc">{h.locator}</span>
          {h.score != null && (
            <span className={`score ${threshold != null ? (below ? 'low' : 'high') : ''}`}>{h.score}</span>
          )}
        </div>
        <div className="hit-text">{h.text}</div>
        {h.parent && (
          <details>
            <summary>回填父块（约 {h.parent.tokens} token）</summary>
            <pre>{h.parent.text}</pre>
          </details>
        )}
      </div>
    </li>
  )
}

function Stage({ title, desc, hits, threshold, open }) {
  return (
    <details className="stage" open={open}>
      <summary>
        <b>{title}</b>
        <span>{desc}</span>
        <em>{hits?.length ?? 0} 条</em>
      </summary>
      {hits?.length ? (
        <ol className="hits">
          {hits.map((h, i) => (
            <Hit key={h.chunk_id + i} h={h} rank={i + 1} threshold={threshold} />
          ))}
        </ol>
      ) : (
        <div className="empty">无</div>
      )}
    </details>
  )
}

export default function SearchTest({ meta }) {
  const [q, setQ] = useState({ query: '', role: 'merchant', platform: '', market: '' })
  const [res, setRes] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const r = meta.retrieval

  const run = async (e) => {
    e?.preventDefault()
    setLoading(true)
    setError('')
    try {
      setRes(await api.search(q))
    } catch (err) {
      setError(err.message)
      setRes(null)
    } finally {
      setLoading(false)
    }
  }

  const set = (k) => (e) => setQ({ ...q, [k]: e.target.value })
  const st = res && STATUS_TEXT[res.status]

  return (
    <>
      <header className="page-head">
        <h1>检索测试</h1>
        <p>
          按身份与适用条件过滤 → 关键词与向量各召回 {r.recall_k} 条 → RRF 融合取 {r.recall_k} 条 → {meta.models.rerank} 重排 → 保留相关分 ≥{' '}
          {r.threshold} → 最多 {r.top_k} 条 → 子块命中时回填父块
        </p>
      </header>
      <form className="card search-form" onSubmit={run}>
        <input className="query" placeholder="输入问题，例如：儿童玩具上架需要什么资质？" value={q.query} onChange={set('query')} />
        <select value={q.role} onChange={set('role')}>
          {Object.entries(meta.roles).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select value={q.platform} onChange={set('platform')}>
          <option value="">不限平台</option>
          {meta.options.platform
            .filter(([k]) => !['general', 'unknown'].includes(k))
            .map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
        </select>
        <select value={q.market} onChange={set('market')}>
          <option value="">不限市场</option>
          {meta.options.market
            .filter(([k]) => k !== 'unknown')
            .map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
        </select>
        <button className="primary" disabled={loading || !q.query.trim()}>
          {loading ? '检索中…' : '检索'}
        </button>
      </form>
      {error && <div className="alert red">{error}</div>}
      {res && (
        <>
          <section className="card summary">
            <Tag cls={st.cls}>{st.text}</Tag>
            <span>{res.role}</span>
            <span>参与检索的块：{res.candidates}</span>
            {res.timing &&
              Object.entries(res.timing).map(([k, v]) => (
                <span key={k}>
                  {k} {v} ms
                </span>
              ))}
            {res.message && <div className="alert gray">{res.message}</div>}
            {res.rerank_error && <div className="alert orange">重排错误：{res.rerank_error}</div>}
            {res.filter.filtered_out.length > 0 && (
              <details>
                <summary>检索前被过滤的文档 {res.filter.filtered_out.length} 份</summary>
                <ul className="log">
                  {res.filter.filtered_out.map((f, i) => (
                    <li key={i}>
                      {f.name} v{f.version}：{f.reason}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </section>
          <section className="card">
            <h2>最终结果（交给大模型作答的依据）</h2>
            {res.final?.length ? (
              <ol className="hits">
                {res.final.map((h, i) => (
                  <Hit key={h.chunk_id} h={h} rank={i + 1} />
                ))}
              </ol>
            ) : (
              <div className="empty">没有达到阈值的片段。前台应回答「知识库中没有找到依据」，并按产品帮助链路转查官网。</div>
            )}
          </section>
          {res.keyword && (
            <section className="card">
              <h2>各阶段明细</h2>
              <Stage
                title={`④ 重排（${meta.models.rerank}）`}
                desc={`灰色为低于 ${res.threshold} 被丢弃`}
                hits={res.reranked}
                threshold={res.threshold}
                open
              />
              <Stage title="③ RRF 融合" desc="两路排名倒数加权，k = 60" hits={res.fused} />
              <Stage title="② 向量召回" desc={`${meta.models.embedding} 余弦相似度，展示前 10`} hits={res.vector} />
              <Stage title="① 关键词召回" desc="BM25，展示前 10" hits={res.keyword} />
            </section>
          )}
        </>
      )}
    </>
  )
}
