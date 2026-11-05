<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { fetchInbox } from '../api/inbox'
import { fetchTrace, resumeThread } from '../api/threads'
import type { InboxItem, TraceResult } from '../types'
import { fmtDateTime, fmtMoney, statusLabel } from '../utils/format'

const router = useRouter()

const items = ref<InboxItem[]>([])
const loading = ref(false)
const selectedId = ref('')
const detail = ref<TraceResult | null>(null)
const detailLoading = ref(false)
const draft = ref('')
const comment = ref('')
const submitting = ref(false)
const lastResult = ref('')

const edited = computed(
  () => detail.value !== null && draft.value.trim() !== (detail.value.reply_draft || '').trim(),
)

async function loadList() {
  loading.value = true
  try {
    const res = await fetchInbox({ status: 'waiting_approval', page: 1, page_size: 50 })
    items.value = res.items
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

async function open(item: InboxItem) {
  selectedId.value = item.thread_id
  detailLoading.value = true
  detail.value = null
  lastResult.value = ''
  try {
    detail.value = await fetchTrace(item.thread_id)
    draft.value = detail.value.reply_draft || ''
    comment.value = ''
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    detailLoading.value = false
  }
}

async function submit(action: 'approve' | 'modify' | 'reject' | 'reassign') {
  if (!detail.value) return
  if (action === 'reject' && !comment.value.trim()) {
    ElMessage.warning('驳回请填写原因')
    return
  }
  submitting.value = true
  try {
    const res = await resumeThread(selectedId.value, {
      action,
      comment: comment.value,
      edited_reply: action === 'approve' && edited.value ? draft.value : undefined,
      approver: '李',
    })
    if (res.pending) {
      lastResult.value = '已带回反馈退回重写，等待再次审批'
      ElMessage.info('已退回重写')
    } else if (res.action === 'reject') {
      lastResult.value = '已驳回'
      ElMessage.warning('已驳回')
    } else if (res.sent) {
      lastResult.value = '已发送'
      ElMessage.success('已发送')
    } else {
      lastResult.value = '已处理（DRY_RUN，未真实发送）'
      ElMessage.success('已处理（DRY_RUN）')
    }
    await loadList()
    if (!items.value.some((i) => i.thread_id === selectedId.value)) {
      detail.value = null
      selectedId.value = ''
    } else {
      detail.value = await fetchTrace(selectedId.value)
      draft.value = detail.value.reply_draft || ''
    }
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    submitting.value = false
  }
}

onMounted(loadList)
</script>

<template>
  <div>
    <div class="topbar">
      <div class="page-title">
        审批台 <span class="sub">{{ items.length }} 单待处理</span>
      </div>
      <div class="top-actions">
        <button class="btn btn-ghost" :disabled="loading" @click="loadList">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </div>
    </div>

    <div v-if="!items.length && !loading" class="panel">
      <div class="empty">
        没有待审批的询盘。到工作台点「模拟投递」选场景 A（超授权）试试。
      </div>
    </div>

    <div v-else class="two-col-wide">
      <div class="panel">
        <div class="panel-hd"><b>待审批列表</b></div>
        <table>
          <thead>
            <tr>
              <th style="width: 42%">客户</th>
              <th>主题</th>
              <th style="width: 92px">时间</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in items"
              :key="item.thread_id"
              class="clickable"
              :class="{ 'row-active': item.thread_id === selectedId }"
              @click="open(item)"
            >
              <td>
                <span class="name">{{ item.customer?.name || item.last_from || '未知' }}</span>
                <span class="sub">{{ item.customer?.email }}</span>
              </td>
              <td>{{ item.subject }}</td>
              <td class="mono">{{ fmtDateTime(item.last_message_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div>
        <div v-if="detailLoading" class="panel"><div class="empty">加载中…</div></div>
        <div v-else-if="!detail" class="panel">
          <div class="empty">从左侧选择一单查看详情</div>
        </div>
        <template v-else>
          <div class="card">
            <h3>{{ detail.subject }}</h3>
            <div class="muted" style="margin-bottom: 10px">
              {{ detail.customer?.name }} &lt;{{ detail.customer?.email }}&gt; ·
              {{ statusLabel(detail.status) }}
            </div>

            <div v-if="detail.quote" class="quote-box">
              <div class="kv">
                <span>产品</span><b>{{ detail.quote.sku }} × {{ detail.quote.qty }}</b>
              </div>
              <div class="kv">
                <span>单价 / 总价</span>
                <b>{{ fmtMoney(detail.quote.unit_price) }} / {{ fmtMoney(detail.quote.total) }}</b>
              </div>
              <div class="kv">
                <span>条款</span>
                <b>{{ detail.quote.incoterm }} {{ detail.quote.destination }}</b>
              </div>
              <div class="kv">
                <span>成本线（内部）</span><b>{{ fmtMoney(detail.quote.floor_price) }}</b>
              </div>
              <div class="kv">
                <span>有效期</span><b>{{ detail.quote.valid_until || '—' }}</b>
              </div>
            </div>

            <div v-if="detail.verdict" style="margin-top: 12px">
              <div class="kv">
                <span>合规结论</span>
                <b>
                  {{ detail.verdict.result }}（{{ detail.verdict.score.toFixed(2) }}）
                </b>
              </div>
              <div v-if="detail.verdict.evidence.length" class="muted" style="margin-top: 4px">
                {{ detail.verdict.evidence.join('；') }}
              </div>
            </div>

            <div v-if="detail.strategy" style="margin-top: 12px">
              <div class="kv">
                <span>策略</span>
                <b>
                  stance={{ detail.strategy.stance }} · adjust={{ detail.strategy.price_adjustment }}
                </b>
              </div>
              <div class="muted" style="margin-top: 4px">{{ detail.strategy.rationale }}</div>
            </div>

            <div v-if="detail.decision" style="margin-top: 12px">
              <div class="kv">
                <span>决策</span><b>{{ detail.decision.action }}</b>
              </div>
              <div class="muted" style="margin-top: 4px">{{ detail.decision.reason }}</div>
            </div>
          </div>

          <div class="card" style="margin-top: 14px">
            <h3>回复草稿（可直接编辑）</h3>
            <textarea v-model="draft" class="draft" rows="12"></textarea>
            <div v-if="detail.fact_check_ok === false" class="warn" style="margin-top: 8px">
              ⚠️ 这份草稿没有通过事实校验，请不要直接发送，建议「按意见重写」。
            </div>
            <div v-if="edited" class="muted" style="margin-top: 6px">
              已编辑：批准时会对编辑后的内容再跑一次事实校验。
            </div>

            <h3 style="margin-top: 14px">审批意见</h3>
            <input v-model="comment" class="search" style="width: 100%" placeholder="驳回必填；改写时可写修改要求" />

            <div class="actions">
              <button class="btn btn-primary" :disabled="submitting" @click="submit('approve')">
                {{ edited ? '校验并发送（含编辑）' : '批准发送' }}
              </button>
              <button class="btn btn-ghost" :disabled="submitting" @click="submit('modify')">
                按意见重写
              </button>
              <button class="btn btn-danger" :disabled="submitting" @click="submit('reject')">
                驳回
              </button>
              <button class="btn btn-ghost" :disabled="submitting" @click="submit('reassign')">
                转他人
              </button>
            </div>
            <div v-if="lastResult" class="muted" style="margin-top: 10px">{{ lastResult }}</div>
          </div>

          <button class="btn btn-ghost" style="margin-top: 12px" @click="router.push(`/threads/${detail.thread_id}/trace`)">
            查看执行轨迹
          </button>
        </template>
      </div>
    </div>
  </div>
</template>
