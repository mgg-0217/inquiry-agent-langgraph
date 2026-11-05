<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { fetchCustomers } from '../api/customers'
import type { CustomerItem } from '../types'
import { fmtDay } from '../utils/format'

const router = useRouter()
const loading = ref(false)
const items = ref<CustomerItem[]>([])
const keyword = ref('')
const total = ref(0)

async function load() {
  loading.value = true
  try {
    const res = await fetchCustomers({ q: keyword.value.trim() || undefined })
    items.value = res.items
    total.value = res.total
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="topbar">
      <div class="page-title">客户记忆 <span class="sub">{{ total }} 个客户</span></div>
      <div class="top-actions">
        <input
          v-model="keyword"
          class="search"
          placeholder="搜索客户名 / 邮箱"
          @input="load"
        />
      </div>
    </div>

    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>客户</th>
            <th style="width: 120px">国家</th>
            <th style="width: 90px">线索数</th>
            <th style="width: 120px">类型</th>
            <th style="width: 110px">创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="5" class="empty">加载中…</td></tr>
          <template v-else>
            <tr
              v-for="row in items"
              :key="row.id"
              class="clickable"
              @click="router.push(`/customers/${row.id}`)"
            >
              <td>
                <span class="name">{{ row.name }}</span>
                <span class="sub">{{ row.email }}</span>
              </td>
              <td>{{ row.country || '—' }}</td>
              <td class="mono">{{ row.thread_count }}</td>
              <td>
                <span class="badge" :class="row.is_new ? 'b-gray' : 'b-ok'">
                  {{ row.is_new ? '新客户' : '老客户' }}
                </span>
              </td>
              <td class="mono">{{ fmtDay(row.created_at) }}</td>
            </tr>
            <tr v-if="!items.length">
              <td colspan="5" class="empty">没有客户</td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
