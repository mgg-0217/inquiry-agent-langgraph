<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { fetchInbox, fetchThread, syncInbox } from '../api/inbox'
import { closeThread, processThread, restoreThread } from '../api/threads'
import { simulateInbound } from '../api/simulate'
import type { InboxItem, Kpis, ThreadDetail } from '../types'

const STATUS_META: Record<string, { label: string; cls: string }> = {
  received: { label: '待处理', cls: 'b-info' },
  triaging: { label: '分诊中', cls: 'b-info' },
  waiting_clarify: { label: '待补充', cls: 'b-warn' },
  processing: { label: '处理中', cls: 'b-info' },
  waiting_approval: { label: '待审批', cls: 'b-warn' },
  replied: { label: '已回复', cls: 'b-ok' },
  archived_spam: { label: '已拦截 · 垃圾', cls: 'b-gray' },
  archived_compliance: { label: '已拦截 · 合规', cls: 'b-red' },
  archived_rejected: { label: '已拒绝', cls: 'b-gray' },
}

const STATUS_TABS = [
  { key: 'all', label: '全部' },
  { key: 'received', label: '待处理' },
  { key: 'waiting_approval', label: '待审批' },
  { key: 'replied', label: '已回复' },
  { key: 'archived', label: '已归档' },
]

const loading = ref(false)
const syncing = ref(false)
const items = ref<InboxItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const kpis = ref<Kpis>({
  today_inbound: 0,
  active_threads: 0,
  waiting_approval: 0,
  avg_first_response_seconds: null,
})

const router = useRouter()
const keyword = ref('')
const statusTab = ref('all')
const simulating = ref('')
const processingId = ref('')

const drawerOpen = ref(false)
const detailLoading = ref(false)
const detail = ref<ThreadDetail | null>(null)

const today = new Date().toLocaleDateString('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

const statusParam = computed(() => {
  if (statusTab.value === 'all') return undefined
  if (statusTab.value === 'archived')
    return 'archived_spam,archived_compliance,archived_rejected'
  return statusTab.value
})

function statusOf(status: string) {
  return STATUS_META[status] ?? { label: status, cls: 'b-gray' }
}

function fmtTime(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  const sameDay = d.toDateString() === new Date().toDateString()
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return sameDay ? hm : `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm}`
}

function fmtSize(bytes: number) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const res = await fetchInbox({
      status: statusParam.value,
      q: keyword.value.trim() || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    items.value = res.items
    total.value = res.total
    kpis.value = res.kpis
  } catch (err) {
    // 自动刷新失败时不打扰用户（后端重启/短暂断网很常见）
    if (!silent) ElMessage.error((err as Error).message)
  } finally {
    if (!silent) loading.value = false
  }
}

let searchTimer: number | undefined
let refreshTimer: number | undefined
function onSearch() {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    page.value = 1
    load()
  }, 280)
}

function switchTab(key: string) {
  statusTab.value = key
  page.value = 1
  load()
}

function onPageChange(p: number) {
  page.value = p
  load()
}

async function onSync() {
  syncing.value = true
  try {
    const report = await syncInbox()
    if (report.created > 0) {
      ElMessage.success(`同步完成，新增 ${report.created} 封邮件`)
    } else if (report.errors.length) {
      ElMessage.warning(`同步完成，有 ${report.errors.length} 封解析失败`)
    } else {
      ElMessage.info('没有新邮件')
    }
    page.value = 1
    await load()
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    syncing.value = false
  }
}

async function runScenario(scenario: string) {
  simulating.value = scenario
  try {
    const res = await simulateInbound(scenario)
    if (res.pending) {
      ElMessage.success(`场景 ${scenario}：已挂起审批（${res.trace.length} 个节点）`)
    } else {
      const tail = res.trace.slice(-2).map((t) => t.node).join(' → ')
      ElMessage.success(`场景 ${scenario}：${tail || '已处理'}`)
    }
    page.value = 1
    await load()
    if (res.thread_id) router.push(`/threads/${res.thread_id}/trace`)
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    simulating.value = ''
  }
}

async function onRestore(item: InboxItem) {
  try {
    const res = await restoreThread(item.thread_id)
    ElMessage.success(`已捞回，当前状态 ${res.status}`)
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function onProcess(item: InboxItem) {
  processingId.value = item.thread_id
  try {
    const res = await processThread(item.thread_id)
    ElMessage.success(res.pending ? '已处理，挂起待审批' : `已处理，状态：${res.status}`)
    await load()
    if (res.pending) {
      router.push('/approvals')
    }
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    processingId.value = ''
  }
}

async function onClose(item: InboxItem) {
  try {
    const res = await closeThread(item.thread_id)
    ElMessage.success(`已关闭（${res.status}）`)
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

function goTrace(item: InboxItem) {
  router.push(`/threads/${item.thread_id}/trace`)
}

async function openThread(item: InboxItem) {
  drawerOpen.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await fetchThread(item.thread_id)
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    detailLoading.value = false
  }
}

onMounted(() => {
  load()
  // 10 秒静默轮询：与后端 IMAP_POLL_INTERVAL 对齐，新邮件无需手动刷新
  refreshTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible' && !loading.value && !syncing.value) {
      load(true)
    }
  }, 10000)
})

onUnmounted(() => {
  window.clearInterval(searchTimer)
  window.clearInterval(refreshTimer)
})
</script>

<template>
  <div>
    <div class="topbar">
      <div class="page-title">
        询盘工作台 <span class="sub">今天 · {{ today }}</span>
      </div>
      <div class="top-actions">
        <div style="display: flex; align-items: center; gap: 6px">
          <span class="muted">模拟投递</span>
          <button
            v-for="s in ['A', 'B', 'C', 'D']"
            :key="s"
            class="btn btn-ghost"
            style="padding: 4px 9px"
            :disabled="!!simulating"
            :title="`场景 ${s}`"
            @click="runScenario(s)"
          >
            {{ simulating === s ? '…' : s }}
          </button>
        </div>
        <input
          v-model="keyword"
          class="search"
          placeholder="搜索客户 / 主题 / 邮箱"
          @input="onSearch"
        />
        <button class="btn btn-ghost" :disabled="syncing" @click="onSync">
          {{ syncing ? '同步中…' : '立即同步' }}
        </button>
        <div class="avatar">李</div>
      </div>
    </div>

    <div class="kpi-grid">
      <div class="kpi">
        <div class="label">今日询盘</div>
        <div class="val">{{ kpis.today_inbound }}<small>封</small></div>
        <div class="delta">实时来自 Mailpit</div>
      </div>
      <div class="kpi">
        <div class="label">活跃线程</div>
        <div class="val">{{ kpis.active_threads }}<small>条</small></div>
        <div class="delta">未归档的对话</div>
      </div>
      <div class="kpi">
        <div class="label">待人工审批</div>
        <div class="val">{{ kpis.waiting_approval }}<small>单</small></div>
        <div class="delta warn" style="cursor: pointer" @click="router.push('/approvals')">
          进入审批台 →
        </div>
      </div>
      <div class="kpi">
        <div class="label">平均首响</div>
        <div class="val">—</div>
        <div class="delta">暂无外发记录</div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-hd">
        <b>全部询盘 <span class="auto-refresh">每 10 秒自动刷新</span></b>
        <div class="tabs">
          <span
            v-for="tab in STATUS_TABS"
            :key="tab.key"
            class="tab"
            :class="{ on: statusTab === tab.key }"
            @click="switchTab(tab.key)"
          >
            {{ tab.label }}
          </span>
        </div>
      </div>

      <table>
        <thead>
          <tr>
            <th style="width: 26%">客户</th>
            <th>主题 / 摘要</th>
            <th style="width: 72px">邮件</th>
            <th style="width: 120px">状态</th>
            <th style="width: 92px">最后动作</th>
            <th style="width: 210px"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="6" class="empty">加载中…</td>
          </tr>
          <template v-else>
            <tr
              v-for="item in items"
              :key="item.thread_id"
              class="clickable"
              @click="openThread(item)"
            >
              <td>
                <span class="name">{{ item.customer?.name || item.last_from || '未知客户' }}</span>
                <span class="sub">{{ item.customer?.email || item.last_from }}</span>
              </td>
              <td>
                <span>{{ item.subject || '(无主题)' }}</span>
                <span v-if="item.last_snippet" class="sub">{{ item.last_snippet }}</span>
              </td>
              <td class="mono">{{ item.message_count }}</td>
              <td>
                <span class="badge" :class="statusOf(item.status).cls">
                  {{ statusOf(item.status).label }}
                </span>
              </td>
              <td class="mono">{{ fmtTime(item.last_message_at) }}</td>
              <td>
                <button
                  v-if="item.status === 'received' || item.status === 'processing'"
                  class="btn btn-primary"
                  style="padding: 4px 9px"
                  :disabled="processingId === item.thread_id"
                  @click.stop="onProcess(item)"
                >
                  {{ processingId === item.thread_id ? '处理中…' : item.status === 'processing' ? '重试' : '处理' }}
                </button>
                <button class="btn btn-ghost" style="padding: 4px 8px" @click.stop="openThread(item)">
                  查看
                </button>
                <button class="btn btn-ghost" style="padding: 4px 8px" @click.stop="goTrace(item)">
                  轨迹
                </button>
                <button
                  v-if="item.status === 'waiting_clarify'"
                  class="btn btn-ghost"
                  style="padding: 4px 8px"
                  @click.stop="onClose(item)"
                >
                  关闭
                </button>
                <button
                  v-if="item.status.startsWith('archived')"
                  class="btn btn-ghost"
                  style="padding: 4px 8px"
                  @click.stop="onRestore(item)"
                >
                  捞回
                </button>
              </td>
            </tr>
            <tr v-if="!items.length">
              <td colspan="6" class="empty">
                暂无询盘。跑
                <code>python scripts/send_test_mail.py</code>
                投一封测试邮件，或点「立即同步」。
              </td>
            </tr>
          </template>
        </tbody>
      </table>

      <div v-if="total > pageSize" class="pager">
        <el-pagination
          layout="total, prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          @current-change="onPageChange"
        />
      </div>
    </div>

    <el-drawer v-model="drawerOpen" size="640px" :with-header="false">
      <button class="drawer-close" title="关闭" @click="drawerOpen = false">✕</button>
      <div v-if="detailLoading" class="empty">加载中…</div>
      <template v-else-if="detail">
        <div class="drawer-title">{{ detail.thread.subject || '(无主题)' }}</div>
        <div class="drawer-meta">
          <span class="badge" :class="statusOf(detail.thread.status).cls">
            {{ statusOf(detail.thread.status).label }}
          </span>
          <span v-if="detail.customer">
            客户：{{ detail.customer.name }} &lt;{{ detail.customer.email }}&gt;
          </span>
          <span>{{ detail.messages.length }} 封邮件</span>
          <span>最后动作：{{ fmtTime(detail.thread.last_message_at) }}</span>
        </div>

        <div v-for="m in detail.messages" :key="m.id" class="mail-card">
          <div class="mail-head">
            <div>
              <b>{{ m.direction === 'inbound' ? '客户来信' : '我方回复' }}</b>
              <div class="mono" style="margin-top: 2px">
                {{ m.from_name || m.from_email }} &lt;{{ m.from_email }}&gt;
              </div>
            </div>
            <span class="mono">{{ fmtTime(m.received_at) }}</span>
          </div>
          <div class="mail-body">{{ m.body_text || '(无纯文本正文)' }}</div>
          <div v-if="m.attachments.length" class="mail-foot">
            <span class="attach" v-for="a in m.attachments" :key="a.filename">
              📎 {{ a.filename }} · {{ fmtSize(a.size) }}
            </span>
          </div>
          <div class="mail-foot">
            <span>Message-ID：{{ m.message_id }}</span>
            <span v-if="m.in_reply_to">In-Reply-To：{{ m.in_reply_to }}</span>
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>
