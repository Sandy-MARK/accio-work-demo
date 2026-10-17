async function request(path, options = {}) {
  const res = await fetch(path, options)
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || `请求失败：HTTP ${res.status}`)
  return body
}

const json = (method, payload) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
})

export const api = {
  meta: () => request('/api/meta'),
  docs: () => request('/api/docs'),
  doc: (id) => request(`/api/docs/${id}`),
  upload: (form) => request('/api/docs', { method: 'POST', body: form }),
  reindex: (id) => request(`/api/docs/${id}/reindex`, { method: 'POST' }),
  review: (id, action) => request(`/api/docs/${id}/review`, json('POST', { action })),
  remove: (id) => request(`/api/docs/${id}`, { method: 'DELETE' }),
  crawls: () => request('/api/crawl'),
  createCrawl: (payload) => request('/api/crawl', json('POST', payload)),
  runCrawl: (id) => request(`/api/crawl/${id}/run`, { method: 'POST' }),
  search: (payload) => request('/api/search', json('POST', payload)),
}
