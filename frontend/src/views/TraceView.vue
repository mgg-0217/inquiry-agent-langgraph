<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchTrace } from '../api/threads'
import type { TraceResult } from '../types'
import { fmtDateTime, statusClass, statusLabel } from '../utils/format'

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const error = ref('')
const data = ref<TraceResult | null>(null)

const dotClass = (status: string) =>
  status === 'ok' ? 'ok' : status === 'error' ? 'err' : 'wait'

const nodeChip = (node: string) => {
  if (node === 'decide') return 'c-dec'
  if (node === 'approval') return 'c-wait'
  return 'c-tool'
}

const pendingText = computed(() =>
  data.value?.pending.length ? data.value.pending.join(', ') : '无',
)

function formatToolArgs(call: { tool: string; args?: unknown; ok?: boolean }) {
  const args = call.args
  const text = args === undefined ? '' : JSON.stringify(args)
  return `${text.length > 80 ? text.slice(0, 80) + '…' : text}${call.ok === false ? '（失败）' : ''}`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchTrace(route.params.id as string)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="topbar">
      <div class="page-title">
        执行轨迹 <span class="sub">{{ data?.subject || '' }}</span>
      </div>
      <div class="top-actions">
        <button class="btn btn-ghost" @click="router.push('/inbox')">返回工作台</button>
        <button
          v-if="data?.pending.length"
          class="btn btn-primary"
          @click="router.push('/approvals')"
        >
          去审批
        </button>
      </div>
    </div>

    <div v-if="loading" class="empty">加载中…</div>
    <div v-else-if="error" class="empty">{{ error }}</div>
    <div v-else-if="data" class="two-col">
      <div class="panel">
        <div class="panel-hd">
          <b>节点时间线</b>
          <span class="badge" :class="statusClass(data.status)">
            {{ statusLabel(data.status) }}
          </span>
        </div>
        <div class="timeline">
          <div v-for="(step, index) in data.steps" :key="index" class="tl">
            <span class="tl-dot" :class="dotClass(step.status)"></span>
            <div class="tl-head">
              <b>{{ step.node }}</b>
              <span class="chip" :class="nodeChip(step.node)">{{ step.status }}</span>
              <span class="time">{{ fmtDateTime(step.started_at) }}</span>
            </div>
            <div class="tl-body">{{ step.summary }}</div>
            <div v-if="step.tool_calls?.length" class="tool-calls">
              <div v-for="(call, ci) in step.tool_calls" :key="ci" class="tool-call">
                <span class="tool-name">🔧 {{ call.tool }}</span>
                <span class="tool-args">{{ formatToolArgs(call) }}</span>
              </div>
            </div>
          </div>
          <div v-if="!data.steps.length" class="empty">
            还没有执行记录。到工作台点「模拟投递」后再来看。
          </div>
        </div>
      </div>

      <div>
        <div class="card">
          <h3>运行信息</h3>
          <div class="kv"><span>线程状态</span><b>{{ statusLabel(data.status) }}</b></div>
          <div class="kv"><span>挂起节点</span><b>{{ pendingText }}</b></div>
          <div class="kv">
            <span>客户</span>
            <b>{{ data.customer?.name || '—' }}</b>
          </div>
          <div class="kv">
            <span>决策</span>
            <b>{{ data.decision?.action || '—' }}</b>
          </div>
          <div class="kv">
            <span>决策理由</span>
            <b style="text-align: right; max-width: 60%">{{ data.decision?.reason || '—' }}</b>
          </div>
          <div class="kv">
            <span>事实校验</span>
            <b>
              {{ data.fact_check_ok === null ? '—' : data.fact_check_ok ? '通过' : '未通过' }}
            </b>
          </div>
        </div>

        <div class="card" style="margin-top: 14px">
          <h3>记忆注入</h3>
          <pre class="mail-body" style="white-space: pre-wrap">{{ data.memory_block || '（本次未注入记忆）' }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>
