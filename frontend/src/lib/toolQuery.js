// Tool arguments are implementation details, not user-facing JSON documents.
export function readableToolQuery(value, depth = 0) {
  if (depth > 3 || value == null) return ''
  if (typeof value === 'string') {
    const text = value.trim()
    if (text === '[object Object]' || text.startsWith('```')) return ''
    if (/^[{[]/.test(text)) {
      try { return readableToolQuery(JSON.parse(text), depth + 1) } catch { return '' }
    }
    return text
  }
  if (typeof value !== 'object' || Array.isArray(value)) return ''
  if (typeof value.query === 'string') return readableToolQuery(value.query, depth + 1)
  const labels = { category: '类别', course_name: '课程', teacher: '教师', points: '积分', content: '内容', reason: '原因' }
  return Object.entries(labels).flatMap(([key, label]) => {
    const item = value[key]
    if (typeof item !== 'string' && typeof item !== 'number') return []
    const text = readableToolQuery(String(item), depth + 1)
    return text ? [`${label}：${text}`] : []
  }).join('；')
}
