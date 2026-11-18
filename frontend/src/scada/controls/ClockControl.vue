<template>
  <div class="ctl clock" :class="{ 'ctl-edit': edit }">
    <div v-if="P.title" class="ttl">{{ P.title }}</div>
    <div v-if="P.showDate" class="date">{{ date }}</div>
    <div class="hm" :style="{ fontSize: hmSize }">{{ time }}</div>
  </div>
</template>

<script setup>
// 时钟控件：只读全局时钟（controls/clock.js），自己不 setInterval。
import { computed, onMounted, onUnmounted } from 'vue'
import { acquireClock, releaseClock, fmtTime } from './clock'

const props = defineProps({ item: { type: Object, required: true }, env: { type: Object, required: true } })
const P = computed(() => props.item.props || {})
const edit = computed(() => props.env.mode === 'edit')

onMounted(acquireClock)
onUnmounted(releaseClock)

// env.clock 是 reactive，读 .n 才建立依赖（只读 .t 在 Vue 里同样能追踪，
// 但显式读版本号更稳，免得以后有人把 clock 换成普通对象）
const now = computed(() => { void props.env.clock.n; return props.env.clock.t })
const time = computed(() => fmtTime(now.value, P.value.format || 'HH:mm:ss', P.value.tz || 'Asia/Shanghai'))
const date = computed(() => fmtTime(now.value, 'yyyy-MM-dd', P.value.tz || 'Asia/Shanghai'))
const hmSize = computed(() => {
  const h = Number(props.item.h) || 80
  return Math.max(12, Math.min(h * 0.5, h * 0.72)) + 'px'
})
</script>

<style scoped>
.ctl { width: 100%; height: 100%; box-sizing: border-box; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 1px; overflow: hidden; }
.ctl-edit { pointer-events: none; }
.ttl { font-size: 11px; color: #9fc3e8; }
.date { font-size: 12px; color: #9fc3e8; letter-spacing: .5px; }
.hm { font-weight: 600; color: #e2e8f0; font-variant-numeric: tabular-nums; letter-spacing: 1px; line-height: 1.1; }
</style>
