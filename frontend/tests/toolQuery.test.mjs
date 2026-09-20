import test from 'node:test'
import assert from 'node:assert/strict'
import { readableToolQuery } from '../src/lib/toolQuery.js'

test('plain queries and legacy JSON arguments become readable summaries', () => {
  assert.equal(readableToolQuery('图书馆开放时间'), '图书馆开放时间')
  assert.equal(readableToolQuery('{"query":"图书馆开放时间"}'), '图书馆开放时间')
  assert.equal(readableToolQuery({ course_name: '机器学习', teacher: '示例教师' }), '课程：机器学习；教师：示例教师')
})

test('unknown, nested, malformed and array arguments never leak as JSON', () => {
  for (const input of ['{"internal":true}', '{"unfinished":', '[{"value":1}]', '[object Object]', { internal: { debug: true } }, { query: { internal: true } }, { query: '{"internal":true}' }]) {
    assert.equal(readableToolQuery(input), '')
  }
})
