<template>
  <div class="about-wrap">
    <el-card shadow="never" class="about-card">
      <div class="brand">
        <div class="brand-cn">张家口陆祺智控工程技术有限责任公司</div>
        <div class="brand-en">luche</div>
      </div>

      <p class="intro">
        专注自动化控制系统集成、工业互联网数据服务与软件开发，为工业制造、市政设施、
        建筑与园区客户提供从方案设计、控制柜成套、系统集成到长期运维的全流程服务。
      </p>

      <div class="contact">
        <div class="contact-row">
          <span class="k">电话</span>
          <a class="v" href="tel:0313-6731626">0313-6731626</a>
          <span class="sep">/</span>
          <a class="v" href="tel:13831341435">13831341435</a>
        </div>
      </div>

      <div class="ver">
        集中监控平台 · 版本 {{ ver }}
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const ver = ref('2026.11')
</script>

<style scoped>
.about-wrap {
  display: flex;
  justify-content: center;
  padding: 40px 20px;
}
.about-card {
  width: 100%;
  max-width: 780px;
  background: #0e1f33;
  border: 1px solid #1e3a52;
}
.brand {
  border-left: 3px solid #1ec8ff;
  padding-left: 14px;
  margin-bottom: 22px;
}
.brand-cn {
  font-size: 21px;
  font-weight: 700;
  color: #e2e8f0;
  letter-spacing: .5px;
}
.brand-en {
  margin-top: 4px;
  font-size: 13px;
  color: #6b8ba6;
  letter-spacing: 1.5px;
}
.intro {
  font-size: 15px;
  line-height: 2;
  color: #b6c7d9;
  margin: 0 0 26px;
  text-indent: 2em;
}
.contact {
  padding: 16px 18px;
  background: #0a1725;
  border: 1px solid #1e3a52;
  border-radius: 6px;
}
.contact-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 15px;
}
.contact-row .k {
  color: #6b8ba6;
  min-width: 40px;
}
.contact-row .v {
  color: #1ec8ff;
  text-decoration: none;
  font-family: Bahnschrift, Consolas, monospace;
}
.contact-row .v:hover { text-decoration: underline; }
.contact-row .sep { color: #3f5570; }
.ver {
  margin-top: 20px;
  font-size: 12px;
  color: #4a6280;
  text-align: right;
}
</style>
