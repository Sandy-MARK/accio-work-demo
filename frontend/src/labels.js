import { createElement } from 'react'

export const STATUS = {
  processing: { text: '处理中', cls: 'blue' },
  indexed: { text: '已入库', cls: 'green' },
  failed: { text: '入库失败', cls: 'red' },
}

export const VALIDITY = {
  active: { text: '生效中', cls: 'green' },
  pending: { text: '未生效', cls: 'gray' },
  repealed: { text: '已失效', cls: 'gray' },
  superseded: { text: '已被替代', cls: 'gray' },
}

export const REVIEW = {
  unreviewed: { text: '待审核', cls: 'orange' },
  approved: { text: '已审核', cls: 'green' },
  rejected: { text: '已驳回', cls: 'red' },
}

export const ROW_STATUS = {
  active: { text: '有效', cls: 'green' },
  expired: { text: '已过期', cls: 'gray' },
  pending: { text: '未生效', cls: 'gray' },
}

export const KIND = { parent: '父块', child: '子块', normal: '普通块' }

export function expectedSteps(knowledgeType, tableKind) {
  const isTable = knowledgeType === 'data_table'
  return [
    '解析',
    ...(isTable ? ['结构化抽取'] : []),
    '切块',
    ...(knowledgeType === 'qa' ? ['问答抽取'] : []),
    '敏感信息检查',
    ...(isTable && tableKind !== 'catalog' ? [] : ['向量化']),
    '建索引',
  ]
}

export function opt(meta, field, value) {
  if (!value) return '—'
  const map = new Map(meta.options[field] ?? [])
  return value
    .split(',')
    .map((v) => map.get(v) ?? v)
    .join('、')
}

export const POLICY = { approved_cloud: '允许在阿里云受控环境处理', local_only: '仅在用户设备处理' }

export function Tag({ cls, children }) {
  return createElement('span', { className: `tag ${cls}` }, children)
}

export function fmtSize(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
