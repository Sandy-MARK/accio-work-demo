async function request(path, options = {}) {
  const res = await fetch(path, options)
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || `请求失败：HTTP ${res.status}`)
  return body
}

export const api = {
  meta: () => request('/api/meta'),
  docs: () => request('/api/docs'),
  doc: (id) => request(`/api/docs/${id}`),
  upload: (form) => request('/api/docs', { method: 'POST', body: form }),
  reindex: (id) => request(`/api/docs/${id}/reindex`, { method: 'POST' }),
  remove: (id) => request(`/api/docs/${id}`, { method: 'DELETE' }),
  search: (payload) =>
    request('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
}
