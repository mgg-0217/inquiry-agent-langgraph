<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const navs = [
  { key: 'inbox', label: '询盘工作台', path: '/inbox', ready: true },
  { key: 'approvals', label: '审批台', path: '/approvals', ready: true },
  { key: 'customers', label: '客户记忆', path: '/customers', ready: true },
  { key: 'eval', label: '评测集', path: '', ready: false },
  { key: 'logs', label: '运行日志', path: '', ready: false },
  { key: 'settings', label: '设置', path: '', ready: false },
]

const activeKey = computed(() => {
  const name = (route.name as string) ?? ''
  if (name === 'trace' || name === 'inbox') return 'inbox'
  if (name === 'customer-memory') return 'customers'
  return name
})
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <span class="logo">IA</span>
      <div>
        <b>Inquiry Agent</b>
        <span>询盘接待智能体</span>
      </div>
    </div>
    <nav>
      <template v-for="item in navs" :key="item.key">
        <router-link
          v-if="item.ready"
          class="nav"
          :class="{ active: activeKey === item.key }"
          :to="item.path"
        >
          {{ item.label }}
        </router-link>
        <span v-else class="nav disabled" title="后续模块开放">{{ item.label }}</span>
      </template>
    </nav>
    <div class="side-foot">
      <div class="env">
        <span>开发环境 · Mailpit 沙箱</span>
        <span class="dot"></span>
      </div>
    </div>
  </aside>
</template>
