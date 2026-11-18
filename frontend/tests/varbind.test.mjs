// 提示词 10 §4.3 · 变量绑定格式单元测试（变量只认 {site, point} 对象）
//
// 跑法（宿主机或 node:20 容器）：
//   docker run --rm -v /opt/plant/frontend:/app -w /app node:20-alpine \
//     node --test tests/
// 只用 node:test + node:assert，不引 vitest/jest —— 不为一条校验多加一套工具链。
//
// 为什么要转一道：`src/scada/varbind.js` 是给 Vite 用的 ESM，而 frontend/package.json
// 没有 "type":"module"（加了会影响 vite.config.js 与构建链）。Node 直接 import 这个 .js
// 会按 CommonJS 解析而报 "Unexpected token 'export'"。这里把它原样复制成 .mjs 再 import，
// 测的还是同一份源码，不复制逻辑、不改构建配置。

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const srcPath = join(here, '..', 'src', 'scada', 'varbind.js')
const tmpDir = mkdtempSync(join(tmpdir(), 'varbind-'))
const tmpFile = join(tmpDir, 'varbind.mjs')
writeFileSync(tmpFile, readFileSync(srcPath, 'utf8'), 'utf8')

const { isValidVar, tagOfVar, invalidVar, collectVarSites, findInvalidVar } =
  await import(pathToFileURL(tmpFile).href)

test('合法变量：{site, point} 两个非空字符串', () => {
  assert.equal(isValidVar({ site: 'S001', point: 'LEVEL' }), true)
  assert.equal(tagOfVar({ site: 'S001', point: 'LEVEL' }), 'S001.LEVEL')
  // 前后空格要吃掉（点位编码从下拉里选，但手改 json 会带空格）
  assert.equal(tagOfVar({ site: ' S001 ', point: ' LEVEL ' }), 'S001.LEVEL')
})

test('非法变量：字符串/表达式/数组/缺字段一律不认（旧格式必须报错，不猜）', () => {
  const bad = [
    'S001.LEVEL',                     // 旧格式字符串
    '@CurrentSite + ".LEVEL"',        // 旧表达式
    '${S001.LEVEL}',                  // 模板字符串写法
    { site: 'S001' },                 // 缺点位
    { point: 'LEVEL' },               // 缺站点
    { site: '', point: 'LEVEL' },     // 空站点
    { site: 'S001', point: '  ' },    // 空白点位
    { site: 1, point: 2 },            // 类型不对
    ['S001', 'LEVEL'],                // 数组
    null, undefined, '', 0
  ]
  for (const v of bad) {
    assert.equal(isValidVar(v), false, '不该通过：' + JSON.stringify(v))
    assert.equal(tagOfVar(v), '', 'tagOfVar 应返回空串：' + JSON.stringify(v))
  }
})

test('invalidVar：没绑变量不算非法，绑了旧格式才算非法', () => {
  assert.equal(invalidVar({ type: 'value' }), false, '没 var 字段 → 不是非法')
  assert.equal(invalidVar({ type: 'value', var: '' }), false, '空 var → 视为没绑')
  assert.equal(invalidVar({ type: 'value', var: null }), false)
  assert.equal(invalidVar({ type: 'value', var: { site: 'S001', point: 'LEVEL' } }), false)
  assert.equal(invalidVar({ type: 'value', var: 'S001.LEVEL' }), true, '旧字符串格式必须判非法')
})

test('collectVarSites：递归收集站点（组合/图层内的对象也要算）', () => {
  const items = [
    { type: 'value', var: { site: 'S001', point: 'LEVEL' } },
    { type: 'group', items: [{ type: 'value', var: { site: 'S002', point: 'PH' } }] },
    { type: 'text' },
    { type: 'value', var: 'S003.OLD' }   // 旧格式不计入
  ]
  assert.deepEqual(collectVarSites(items).sort(), ['S001', 'S002'])
  assert.deepEqual(collectVarSites([]), [])
  assert.deepEqual(collectVarSites(null), [])
})

test('findInvalidVar：找到第一个旧格式对象（ViewPage 据此报「变量格式错误」并拒绝渲染）', () => {
  const okPage = [{ type: 'value', var: { site: 'S001', point: 'LEVEL' } }]
  assert.equal(findInvalidVar(okPage), null)

  const badItem = { type: 'value', name: '液位', var: 'S001.LEVEL' }
  const hit = findInvalidVar([{ type: 'text' }, { type: 'group', items: [badItem] }])
  assert.equal(hit, badItem, '嵌套在组合里的旧格式也要抓到')
})
