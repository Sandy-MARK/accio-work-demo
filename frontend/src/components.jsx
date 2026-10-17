export function Select({ meta, field, label, value, onChange, options }) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(field, e.target.value)}>
        {(options ?? meta.options[field]).map(([k, v]) => (
          <option key={k} value={k}>
            {v}
          </option>
        ))}
      </select>
    </label>
  )
}

export function DeptPicker({ meta, value, onChange }) {
  const picked = value ? value.split(',') : []
  const toggle = (k) => {
    const next = picked.includes(k) ? picked.filter((x) => x !== k) : [...picked, k]
    onChange('dept_ids', next.join(','))
  }
  return (
    <div className="field">
      <span>可见部门</span>
      <div className="checks">
        {meta.options.dept_ids.map(([k, v]) => (
          <label key={k}>
            <input type="checkbox" checked={picked.includes(k)} onChange={() => toggle(k)} />
            {v}
          </label>
        ))}
      </div>
    </div>
  )
}

export function accessOptions(meta, space) {
  const allowed = meta.spaces[space].access
  return meta.options.access_level.filter(([k]) => allowed.includes(k))
}
