import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { DeptPicker, Select, accessOptions } from '../components.jsx'
import { Tag, opt } from '../labels.js'

const DEFAULTS = {
  knowledge_space_id: 'kb_help',
  knowledge_type: 'guide',
  source_type: 'help_doc',
  access_level: 'public',
  dept_ids: '',
  business_domain: 'common',
  platform: 'general',
  market: 'unknown',
  language: 'en',
  quality_grade: 'reviewed',
  risk_level: 'normal',
}

const RESULT = [
  ['new', '新增', 'green'],
  ['updated', '有变化，生成新版本', 'blue'],
  ['unchanged', '未变化，跳过', 'gray'],
  ['gaps', '缺口', 'orange'],
  ['failed', '失败', 'red'],
]

function Result({ res }) {
  if (!res) return <span className="sub">尚未同步</span>
  return (
    <div className="crawl-result">
      <div className="crawl-counts">
        <span>共 {res.pages} 页</span>
        {RESULT.map(([k, l, cls]) =>
          res[k].length ? (
            <Tag key={k} cls={cls}>
              {l} {res[k].length}
            </Tag>
          ) : null,
        )}
      </div>
      {res.error && <div className="alert red">{res.error}</div>}
      <details>
        <summary>逐页明细</summary>
        <ul className="log">
          {RESULT.flatMap(([k, l]) =>
            res[k].map((x) => (
              <li key={k + x.url} className={k === 'gaps' || k === 'failed' ? 'warn' : ''}>
                <b>{l}</b> {x.name || ''} <code>{x.url}</code>
                {x.version && ` v${x.version}`}
                {x.reason && `：${x.reason}`}
              </li>
            )),
          )}
        </ul>
      </details>
    </div>
  )
}

export default function Crawl({ meta }) {
  const [url, setUrl] = useState('')
  const [mode, setMode] = useState('sitemap')
  const [form, setForm] = useState(DEFAULTS)
  const [sources, setSources] = useState([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const load = () => api.crawls().then(setSources)

  useEffect(() => {
    load()
  }, [])

  const set = (field, value) =>
    setForm((f) =>
      field === 'knowledge_space_id'
        ? { ...f, [field]: value, access_level: meta.spaces[value].access[0], dept_ids: '' }
        : { ...f, [field]: value },
    )

  const run = async (key, fn) => {
    setBusy(key)
    setError('')
    try {
      await fn()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy('')
      load()
    }
  }

  return (
    <>
      <header className="page-head">
        <h1>网页抓取</h1>
        <p>
          输入单个页面、站点地图或目录页，逐页抓取正文入库（单次最多 30 页，遵守站点 robots.txt）。再次同步时按正文内容比对：未变化的页面跳过，有变化的生成新版本；没有正文的页面记为缺口。
        </p>
      </header>
      <section className="card">
        <h2>新增抓取来源</h2>
        <div className="crawl-form">
          <input className="query" placeholder="https://… 例如帮助中心的 sitemap.xml" value={url} onChange={(e) => setUrl(e.target.value)} />
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            {Object.entries(meta.crawl_modes).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
        <div className="form-grid">
          <Select meta={meta} field="knowledge_space_id" label="知识空间" value={form.knowledge_space_id} onChange={set} />
          <Select
            meta={meta}
            field="knowledge_type"
            label="知识类型"
            value={form.knowledge_type}
            onChange={set}
            options={meta.options.knowledge_type.filter(([k]) => k !== 'data_table')}
          />
          <Select meta={meta} field="access_level" label="权限" value={form.access_level} onChange={set} options={accessOptions(meta, form.knowledge_space_id)} />
          {form.access_level === 'department' && <DeptPicker meta={meta} value={form.dept_ids} onChange={set} />}
          <Select meta={meta} field="source_type" label="来源类型" value={form.source_type} onChange={set} />
          <Select meta={meta} field="business_domain" label="业务域" value={form.business_domain} onChange={set} />
          <Select meta={meta} field="platform" label="平台" value={form.platform} onChange={set} />
          <Select meta={meta} field="language" label="语言" value={form.language} onChange={set} />
          <Select meta={meta} field="quality_grade" label="质量等级" value={form.quality_grade} onChange={set} />
        </div>
        <div className="row-end">
          <span className="hint">
            {meta.spaces[form.knowledge_space_id].review ? '抓取入库的平台公共知识为「待审核」，需在文档管理中审核通过后参与检索。' : ''}
          </span>
          <button
            className="primary"
            disabled={!!busy || !url.trim()}
            onClick={() => run('new', () => api.createCrawl({ url: url.trim(), mode, meta: form }))}
          >
            {busy === 'new' ? '抓取中…' : '添加并抓取'}
          </button>
        </div>
        {error && <div className="alert red">{error}</div>}
      </section>
      <section className="card">
        <h2>抓取来源</h2>
        {sources.length === 0 ? (
          <div className="empty">还没有抓取来源</div>
        ) : (
          <div className="sources">
            {sources.map((s) => (
              <div key={s.source_id} className="source">
                <div className="source-head">
                  <div>
                    <code>{s.url}</code>
                    <div className="sub">
                      {meta.crawl_modes[s.mode]} · {opt(meta, 'knowledge_space_id', s.meta.knowledge_space_id)} ·{' '}
                      {opt(meta, 'knowledge_type', s.meta.knowledge_type)} · 上次同步 {s.last_run_at?.replace('T', ' ') ?? '—'}
                    </div>
                  </div>
                  <button disabled={!!busy} onClick={() => run(s.source_id, () => api.runCrawl(s.source_id))}>
                    {busy === s.source_id ? '同步中…' : '立即同步'}
                  </button>
                </div>
                <Result res={s.last_result} />
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  )
}
