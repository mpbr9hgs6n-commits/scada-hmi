// 提示词 11 · deck.js 单元测试（介质颜色 / 质量码三态 / 调试参数）
//
// 跑法（同 varbind.test.mjs 的复制技巧，deck.js 依赖 import.meta.env，要先剥掉）：
//   node --test tests/deck.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))

// 复制源码成 .mjs；import.meta.env 只在 DECK_DEBUG 里用，Node 下是 undefined →
// 用一个假全局兜住（PROD=false 分支），不改动被测逻辑本身。
const src = readFileSync(join(here, '../src/scada/deck.js'), 'utf-8')
const tmp = mkdtempSync(join(tmpdir(), 'deck-'))
const tmpFile = join(tmp, 'deck.mjs')
writeFileSync(tmpFile, src.replace(
  'typeof import.meta !== \'undefined\' && import.meta.env && import.meta.env.PROD',
  'false'
), 'utf-8')
const { MEDIUM, mediumOf, boundState, displayOf, DOT_OF } = await import(pathToFileURL(tmpFile).href)

const NOW = 1794300000000

test('介质枚举：进水和出水的颜色必须不同（原则 3 的直接验证）', () => {
  assert.notEqual(MEDIUM.influent.color, MEDIUM.effluent.color)
  assert.notEqual(MEDIUM.sludge.color, MEDIUM.effluent.color)
})

test('mediumOf：未配置回落清水，配错键也回落（组件不许裸奔）', () => {
  assert.equal(mediumOf({}).color, MEDIUM.clean.color)
  assert.equal(mediumOf({ medium: '不存在' }).color, MEDIUM.clean.color)
  assert.equal(mediumOf({ medium: 'sludge' }).color, MEDIUM.sludge.color)
})

test('三态：q=1 是 bad（读失败），显示 -- 不是 0', () => {
  const r = displayOf({ val: 3.2, ts: NOW, q: 1 }, NOW)
  assert.equal(r.state, 'bad')
  assert.equal(r.display, '--')
  assert.equal(r.dot, DOT_OF.bad)
})

test('三态：超 3 秒没更新是 stale（站点离线 → 整站自然冻结）', () => {
  const r = displayOf({ val: 3.2, ts: NOW - 4000, q: 0 }, NOW)
  assert.equal(r.state, 'stale')
  assert.equal(r.display, '--')
  const ok = displayOf({ val: 3.2, ts: NOW - 2000, q: 0 }, NOW)
  assert.equal(ok.state, 'good')
  assert.equal(ok.display, 3.2)
})

test('三态：没有记录是 nodata；ts 缺失按 stale 处理', () => {
  assert.equal(boundState(null, NOW).state, 'nodata')
  assert.equal(boundState({ val: 1, q: 0 }, NOW).state, 'stale')
})

test('三态：val 为 null 是 bad（网关断线写 q=1/空值，不许当 0）', () => {
  assert.equal(boundState({ val: null, ts: NOW, q: 0 }, NOW).state, 'bad')
})

test('状态点色语义唯一：绿正常 琥珀超时 灰离线（不给颜色第二含义）', () => {
  assert.equal(DOT_OF.good, '#2fd67e')
  assert.equal(DOT_OF.stale, '#f5aa39')
  assert.equal(DOT_OF.bad, DOT_OF.nodata)   // bad 与 nodata 都是灰
})
