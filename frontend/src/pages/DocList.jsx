import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { DeptPicker, Select, accessOptions } from '../components.jsx'
import { REVIEW, STATUS, Tag, VALIDITY, expectedSteps, fmtSize, opt } from '../labels.js'

const SPACE_PRESET = {
  kb_platform_rules: { knowledge_type: 'rule', source_type: 'official_rule', quality_grade: 'reviewed', business_domain: 'listing' },
  kb_help: { knowledge_type: 'qa', source_type: 'help_doc', quality_grade: 'reviewed', business_domain: 'common' },
  kb_team_demo: { knowledge_type: 'data_table', source_type: 'user_upload', quality_grade: 'candidate', business_domain: 'sourcing' },
  kb_user_demo: { knowledge_type: 'manual', source_type: 'user_upload', quality_grade: 'candidate', business_domain: 'sourcing' },
}

const DEFAULTS = {
  knowledge_space_id: 'kb_platform_rules',
  ...SPACE_PRESET.kb_platform_rules,
  table_kind: 'catalog',
  access_level: 'public',
  dept_ids: '',
  platform: 'general',
  market: 'unknown',
  language: 'zh',
  risk_level: 'normal',
  effective_from: '',
  expires_at: '',
}

function StepBar({ names, steps, running }) {
  return (
    <div className="steps">
      {names.map((name, i) => {
        const s = steps?.find((x) => x.name === name)
        const failedBefore = steps?.some((x) => !x.ok && names.indexOf(x.name) < i)
        const state = s ? (s.ok ? 'done' : 'fail') : running && !failedBefore ? 'run' : 'idle'
        return (
          <div key={name} className={`step ${state}`}>
            <div className="dot">{state === 'done' ? '✓' : state === 'fail' ? '!' : i + 1}</div>
            <div className="step-body">
              <div className="step-name">
                {name}
                {s && <em>{s.ms} ms</em>}
              </div>
              {s && <div className="step-detail">{s.detail}</div>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function UploadPanel({ meta, onDone }) {
  const [form, setForm] = useState(DEFAULTS)
  const [file, setFile] = useState(null)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const strategy = meta.strategies[form.knowledge_type]
  const space = meta.spaces[form.knowledge_space_id]
  const isTable = form.knowledge_type === 'data_table'

  const set = (field, value) => {
    setForm((f) =>
      field === 'knowledge_space_id'
        ? { ...f, [field]: value, ...SPACE_PRESET[value], access_level: meta.spaces[value].access[0], dept_ids: '' }
        : { ...f, [field]: value },
    )
  }

  const submit = async () => {
    if (!file) return setError('请选择文件')
    setError('')
    setResult(null)
    setRunning(true)
    const fd = new FormData()
    fd.append('file', file)
    Object.entries(form).forEach(([k, v]) => fd.append(k, v))
    try {
      const r = await api.upload(fd)
      setResult(r)
      onDone()
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <section className="card">
      <h2>上传文档</h2>
      <div className="upload-grid">
        <div>
          <label className="drop">
            <input
              type="file"
              accept={isTable ? '.xlsx,.csv' : '.md,.txt,.pdf,.docx,.xlsx,.csv,.html,.htm'}
              onChange={(e) => setFile(e.target.files[0])}
            />
            {file ? (
              <span>
                {file.name}（{fmtSize(file.size)}）
              </span>
            ) : (
              <span>
                {isTable
                  ? '点击选择表格文件：Excel / CSV，≤20 MB'
                  : '点击选择文件：PDF / Word / Excel / CSV / Markdown / TXT / 网页，≤20 MB'}
              </span>
            )}
          </label>
          <div className="form-grid">
            <Select meta={meta} field="knowledge_space_id" label="知识空间" value={form.knowledge_space_id} onChange={set} />
            <Select meta={meta} field="knowledge_type" label="知识类型" value={form.knowledge_type} onChange={set} />
            {isTable && <Select meta={meta} field="table_kind" label="表格类别" value={form.table_kind} onChange={set} />}
            <Select
              meta={meta}
              field="access_level"
              label="权限（只能比空间默认更严）"
              value={form.access_level}
              onChange={set}
              options={accessOptions(meta, form.knowledge_space_id)}
            />
            {form.access_level === 'department' && <DeptPicker meta={meta} value={form.dept_ids} onChange={set} />}
            <Select meta={meta} field="source_type" label="来源类型" value={form.source_type} onChange={set} />
            <Select meta={meta} field="business_domain" label="业务域" value={form.business_domain} onChange={set} />
            <Select meta={meta} field="platform" label="平台" value={form.platform} onChange={set} />
            <Select meta={meta} field="market" label="目标市场" value={form.market} onChange={set} />
            <Select meta={meta} field="language" label="语言" value={form.language} onChange={set} />
            <Select meta={meta} field="quality_grade" label="质量等级" value={form.quality_grade} onChange={set} />
            <Select meta={meta} field="risk_level" label="风险等级" value={form.risk_level} onChange={set} />
            <label className="field">
              <span>生效日期</span>
              <input type="date" value={form.effective_from} onChange={(e) => set('effective_from', e.target.value)} />
            </label>
            <label className="field">
              <span>失效日期</span>
              <input type="date" value={form.expires_at} onChange={(e) => set('expires_at', e.target.value)} />
            </label>
          </div>
        </div>
        <div className="strategy">
          <h3>该类型的处理规则</h3>
          <dl>
            <dt>知识层</dt>
            <dd>{space.layer}</dd>
            <dt>文档类型</dt>
            <dd>{strategy.label}</dd>
            <dt>切法</dt>
            <dd>{strategy.strategy}</dd>
            <dt>块大小</dt>
            <dd>{strategy.size}</dd>
            <dt>父子块</dt>
            <dd>{strategy.parent_child}</dd>
          </dl>
          {isTable && (
            <p className="hint">
              表头按同义词自动映射为标准字段：
              {meta.table_fields[form.table_kind].map(([, l]) => l).join('、')}。未识别的列保留为附加字段。
            </p>
          )}
          <p className="hint">
            {space.review ? '平台公共知识入库后为「待审核」，审核通过才参与检索。' : '企业与个人知识入库即可检索，无需审核。'}
            同一空间内同名文件生成新版本；内容完全相同的文件不重复入库。
          </p>
          <button className="primary" disabled={running} onClick={submit}>
            {running ? '入库中…' : '上传并入库'}
          </button>
        </div>
      </div>
      {error && <div className="alert red">{error}</div>}
      {(running || result) && (
        <StepBar names={expectedSteps(form.knowledge_type, form.table_kind)} steps={result?.steps} running={running} />
      )}
      {result?.status === 'failed' && <div className="alert red">入库失败：{result.error}</div>}
      {result?.status === 'indexed' && (
        <div className="alert green">
          已入库：{result.name} v{result.version}
          {result.review_status === 'unreviewed' && '，待审核通过后参与检索'}
        </div>
      )}
    </section>
  )
}

function counts(d) {
  const parts = []
  if (d.chunk_count) parts.push(`${d.chunk_count} 块`)
  if (d.row_count) parts.push(`${d.row_count} 行`)
  if (d.qa_count) parts.push(`${d.qa_count} 问答`)
  return parts.join(' · ') || '—'
}

export default function DocList({ meta, onOpen }) {
  const [docs, setDocs] = useState([])
  const [space, setSpace] = useState('')
  const [busy, setBusy] = useState('')
  const load = () => api.docs().then(setDocs)

  useEffect(() => {
    load()
  }, [])

  const act = async (id, fn) => {
    setBusy(id)
    try {
      await fn()
    } catch (e) {
      alert(e.message)
    } finally {
      setBusy('')
      load()
    }
  }

  const shown = space ? docs.filter((d) => d.knowledge_space_id === space) : docs
  const pending = docs.filter((d) => d.review_status === 'unreviewed' && d.status === 'indexed').length

  return (
    <>
      <header className="page-head">
        <h1>文档管理</h1>
        <p>
          上传 → 解析 → 切块 / 结构化抽取 / 问答抽取 → 敏感信息检查 → 向量化 → 建索引。每份文档按知识类型套用对应处理规则，并写入元数据用于权限与适用条件过滤。
        </p>
      </header>
      <UploadPanel meta={meta} onDone={load} />
      <section className="card">
        <div className="card-head">
          <h2>
            文档列表 {pending > 0 && <Tag cls="orange">{pending} 份待审核</Tag>}
          </h2>
          <select value={space} onChange={(e) => setSpace(e.target.value)}>
            <option value="">全部知识空间</option>
            {meta.options.knowledge_space_id.map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
        {shown.length === 0 ? (
          <div className="empty">还没有文档。可以先上传 samples 目录里的示例文档。</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>文档</th>
                  <th>知识空间</th>
                  <th>知识类型</th>
                  <th>权限</th>
                  <th>平台 / 市场</th>
                  <th>内容</th>
                  <th>状态</th>
                  <th>审核</th>
                  <th>效力</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {shown.map((d) => (
                  <tr key={d.doc_version_id}>
                    <td>
                      <button className="link" onClick={() => onOpen(d.doc_version_id)}>
                        {d.name}
                      </button>
                      <div className="sub">
                        v{d.version} · {fmtSize(d.size)} · {d.created_at.replace('T', ' ')}
                        {d.pii_level === 'high' && ' · 含个人信息'}
                      </div>
                    </td>
                    <td>{opt(meta, 'knowledge_space_id', d.knowledge_space_id)}</td>
                    <td>
                      {opt(meta, 'knowledge_type', d.knowledge_type)}
                      {d.table_kind && <div className="sub">{opt(meta, 'table_kind', d.table_kind)}</div>}
                    </td>
                    <td>
                      {opt(meta, 'access_level', d.access_level)}
                      {d.dept_ids && <div className="sub">{opt(meta, 'dept_ids', d.dept_ids)}</div>}
                    </td>
                    <td>
                      {opt(meta, 'platform', d.platform)} / {opt(meta, 'market', d.market)}
                    </td>
                    <td>{counts(d)}</td>
                    <td>
                      <Tag cls={STATUS[d.status].cls}>{STATUS[d.status].text}</Tag>
                    </td>
                    <td>
                      <Tag cls={REVIEW[d.review_status].cls}>{REVIEW[d.review_status].text}</Tag>
                    </td>
                    <td>
                      <Tag cls={VALIDITY[d.validity_status].cls}>{VALIDITY[d.validity_status].text}</Tag>
                    </td>
                    <td className="ops">
                      {meta.spaces[d.knowledge_space_id].review && d.status === 'indexed' && d.review_status !== 'approved' && (
                        <button disabled={busy === d.doc_version_id} onClick={() => act(d.doc_version_id, () => api.review(d.doc_version_id, 'approve'))}>
                          审核通过
                        </button>
                      )}
                      {meta.spaces[d.knowledge_space_id].review && d.review_status === 'unreviewed' && (
                        <button disabled={busy === d.doc_version_id} onClick={() => act(d.doc_version_id, () => api.review(d.doc_version_id, 'reject'))}>
                          驳回
                        </button>
                      )}
                      {d.status === 'failed' && d.processing_policy !== 'local_only' && (d.chunk_count > 0 || d.qa_count > 0) && (
                        <button disabled={busy === d.doc_version_id} onClick={() => act(d.doc_version_id, () => api.reindex(d.doc_version_id))}>
                          重新向量化
                        </button>
                      )}
                      <button
                        className="danger"
                        disabled={busy === d.doc_version_id}
                        onClick={() => confirm(`删除 ${d.name} v${d.version}？`) && act(d.doc_version_id, () => api.remove(d.doc_version_id))}
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
      </section>
    </>
  )
}
