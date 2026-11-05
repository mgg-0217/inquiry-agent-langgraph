<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { correctFact, fetchCustomer, fetchMemory } from '../api/customers'
import type { CustomerDetail, FactItem } from '../types'
import { fmtDay, fmtDateTime, statusClass, statusLabel } from '../utils/format'

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const detail = ref<CustomerDetail | null>(null)
const memoryBlock = ref('')
const editingId = ref('')
const editingValue = ref('')

async function load() {
  loading.value = true
  try {
    const id = route.params.id as string
    detail.value = await fetchCustomer(id)
    const memory = await fetchMemory(id)
    memoryBlock.value = memory.block
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

async function invalidate(fact: FactItem) {
  if (!detail.value) return
  try {
    await correctFact(detail.value.customer.id, fact.id, { action: 'invalidate' })
    ElMessage.success('已标记失效（不再召回，保留审计）')
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

function startEdit(fact: FactItem) {
  editingId.value = fact.id
  editingValue.value = fact.value
}

async function saveEdit(fact: FactItem) {
  if (!detail.value) return
  if (!editingValue.value.trim()) {
    ElMessage.warning('值不能为空')
    return
  }
  try {
    await correctFact(detail.value.customer.id, fact.id, {
      action: 'update',
      value: editingValue.value.trim(),
    })
    editingId.value = ''
    ElMessage.success('已更新（旧记录保留，可追溯）')
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="topbar">
      <div class="page-title">
        客户记忆 <span class="sub">{{ detail?.customer.name || '' }}</span>
      </div>
      <div class="top-actions">
        <button class="btn btn-ghost" @click="router.push('/customers')">返回列表</button>
      </div>
    </div>

    <div v-if="loading" class="empty">加载中…</div>
    <div v-else-if="!detail" class="empty">客户不存在</div>
    <div v-else class="three-col">
      <div>
        <div class="card">
          <div class="profile">
            <div class="ava">{{ detail.customer.name.slice(0, 2) }}</div>
            <div>
              <h3 style="margin: 0">{{ detail.customer.name }}</h3>
              <div class="muted">{{ detail.customer.email }}</div>
              <div class="muted">
                {{ detail.customer.country || '—' }} ·
                {{ detail.customer.is_new ? '新客户' : '老客户' }} ·
                {{ detail.customer.thread_count }} 条线索
              </div>
            </div>
          </div>
          <div class="tags">
            <span class="tag" v-for="fact in detail.facts.filter((f) => !f.superseded_by).slice(0, 6)" :key="fact.id">
              {{ fact.key }}={{ fact.value }}
            </span>
          </div>
        </div>

        <div class="panel" style="margin-top: 14px">
          <div class="panel-hd"><b>记忆事实</b><span class="muted">置信度 / 有效期 / 证据</span></div>
          <table>
            <thead>
              <tr>
                <th style="width: 96px">key</th>
                <th>值 / 证据</th>
                <th style="width: 116px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="fact in detail.facts" :key="fact.id">
                <td class="mono">{{ fact.key }}</td>
                <td>
                  <template v-if="editingId === fact.id">
                    <input v-model="editingValue" class="search" style="width: 100%" />
                  </template>
                  <template v-else>
                    <span :class="{ 'text-muted': !!fact.superseded_by }">{{ fact.value }}</span>
                    <span class="sub" v-if="fact.evidence">证据：{{ fact.evidence }}</span>
                    <span class="sub">
                      置信度 {{ fact.confidence.toFixed(2) }}
                      <template v-if="fact.valid_until">· 有效期 {{ fmtDay(fact.valid_until) }}</template>
                    </span>
                    <span class="sub" v-if="fact.superseded_by">已失效（人工纠正/被取代）</span>
                  </template>
                </td>
                <td>
                  <template v-if="!fact.superseded_by">
                    <template v-if="editingId === fact.id">
                      <button class="btn btn-primary" style="padding: 4px 8px" @click="saveEdit(fact)">保存</button>
                      <button class="btn btn-ghost" style="padding: 4px 8px" @click="editingId = ''">取消</button>
                    </template>
                    <template v-else>
                      <button class="btn btn-ghost" style="padding: 4px 8px" @click="startEdit(fact)">改值</button>
                      <button class="btn btn-danger" style="padding: 4px 8px" @click="invalidate(fact)">失效</button>
                    </template>
                  </template>
                  <span class="muted" v-else>—</span>
                </td>
              </tr>
              <tr v-if="!detail.facts.length">
                <td colspan="3" class="empty">暂无记忆事实</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <div class="card">
          <h3>注入模型用的记忆块</h3>
          <pre class="mail-body" style="white-space: pre-wrap">{{ memoryBlock || '（无记忆）' }}</pre>
        </div>

        <div class="card" style="margin-top: 14px">
          <h3>交互时间线</h3>
          <div class="timeline">
            <div v-for="item in detail.interactions" :key="item.id" class="tl">
              <span class="tl-dot ok"></span>
              <div class="tl-head">
                <b>{{ item.outcome }}</b>
                <span class="chip" :class="item.lost_reason ? 'c-wait' : 'c-ok'">
                  {{ item.lost_reason || '—' }}
                </span>
                <span class="time">{{ fmtDateTime(item.created_at) }}</span>
              </div>
              <div class="tl-body">{{ item.summary }}</div>
              <div class="tl-body muted" v-if="item.evidence">客户原话：“{{ item.evidence }}”</div>
            </div>
            <div v-if="!detail.interactions.length" class="empty">暂无交互记录</div>
          </div>
        </div>
      </div>

      <div class="card">
        <h3>线索</h3>
        <div
          v-for="thread in detail.threads"
          :key="thread.id"
          class="thread-row"
          @click="router.push(`/threads/${thread.id}/trace`)"
        >
          <div style="font-weight: 600; font-size: 12.5px">{{ thread.subject }}</div>
          <div style="margin-top: 4px">
            <span class="badge" :class="statusClass(thread.status)">
              {{ statusLabel(thread.status) }}
            </span>
            <span class="mono" style="margin-left: 8px">{{ fmtDay(thread.last_message_at) }}</span>
          </div>
        </div>
        <div v-if="!detail.threads.length" class="empty">暂无线索</div>
      </div>
    </div>
  </div>
</template>
