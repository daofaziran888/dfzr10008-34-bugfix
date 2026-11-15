<template>
  <section class="page" data-module="feedback">
    <header class="page-head">
      <div>
        <h2>数据质量反馈管理</h2>
        <p class="page-desc">维护数据质量反馈的类型分类、严重度评估与处理追踪，为数据质量反馈提供可验证的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记反馈记录</button>
        <button class="btn" type="button" @click="exportRows">导出数据质量反馈清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>反馈编号</span>
        <input v-model="keyword" placeholder="按反馈编号检索" />
      </label>
      <label class="filter-item">
        <span>处理状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!availableActions(row).length" class="muted-text">已关闭</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无数据质量反馈数据，可先登记反馈记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据质量反馈记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="createVisible" class="modal-mask" @click.self="createVisible = false">
      <form class="modal-card" @submit.prevent="submitCreate">
        <h3>登记反馈记录</h3>
        <label v-for="field in createFields" :key="field.key" class="form-item">
          <span>{{ field.label }}<em v-if="field.required" class="required-mark">*</em></span>
          <select v-if="field.key === '严重程度'" v-model="createForm[field.key]">
            <option value="">请选择</option>
            <option v-for="level in severityLevels" :key="level" :value="level">{{ level }}</option>
          </select>
          <textarea v-else-if="field.key === '反馈内容'" v-model="createForm[field.key]" rows="3" />
          <input v-else v-model="createForm[field.key]" :placeholder="`请输入${field.label}`" />
        </label>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="modal-actions">
          <button class="btn primary" type="submit">保存</button>
          <button class="btn ghost" type="button" @click="createVisible = false">取消</button>
        </div>
      </form>
    </div>

    <div v-if="actionDialog.visible" class="modal-mask" @click.self="actionDialog.visible = false">
      <form class="modal-card" @submit.prevent="submitAction">
        <h3>{{ actionDialog.action }} · {{ actionDialog.row?.['反馈编号'] }}</h3>
        <label class="form-item">
          <span>处理人</span>
          <input v-model="actionDialog.处理人" placeholder="请输入处理人" />
        </label>
        <label class="form-item">
          <span>解决轨迹<em v-if="actionDialog.action === '标记解决'" class="required-mark">*</em></span>
          <textarea v-model="actionDialog.解决轨迹" rows="3" placeholder="记录校验批次、抽查行数、异常行号等处理过程" />
        </label>
        <p v-if="actionDialog.error" class="error-text">{{ actionDialog.error }}</p>
        <div class="modal-actions">
          <button class="btn primary" type="submit">确认{{ actionDialog.action }}</button>
          <button class="btn ghost" type="button" @click="actionDialog.visible = false">取消</button>
        </div>
      </form>
    </div>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal-card">
        <h3>反馈详情 · {{ detail['反馈编号'] }}</h3>
        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd>{{ detail[field] || '—' }}</dd>
          </template>
        </dl>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/feedback'
const columns = ["反馈编号", "数据产品", "反馈类型", "反馈内容", "严重程度", "处理状态", "反馈人", "反馈时间", "解决轨迹"]
const detailFields = ["反馈编号", "数据产品", "反馈类型", "反馈内容", "严重程度", "处理状态", "反馈人", "反馈时间", "解决轨迹", "处理人", "处理时间"]
const statuses = ["待处理", "处理中", "已解决", "已关闭"]
const severityLevels = ["高", "中", "低"]
// 状态机单向推进：每个状态只暴露可执行的动作，已关闭不能重开
const STATUS_ACTIONS: Record<string, string[]> = {
  "待处理": ["开始处理"],
  "处理中": ["标记解决"],
  "已解决": ["关闭反馈"],
  "已关闭": [],
}
const createFields = [
  { key: "反馈编号", label: "反馈编号", required: true },
  { key: "数据产品", label: "数据产品", required: true },
  { key: "反馈类型", label: "反馈类型", required: true },
  { key: "反馈内容", label: "反馈内容", required: false },
  { key: "严重程度", label: "严重程度", required: false },
  { key: "反馈人", label: "反馈人", required: false },
  { key: "反馈时间", label: "反馈时间", required: false },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const stats = ref([{ label: '反馈记录总数', value: 0 }, { label: '处理中反馈', value: 0 }, { label: '已解决反馈', value: 0 }])

const createVisible = ref(false)
const createForm = reactive<Record<string, string>>({})
const createError = ref('')
const detail = ref<Row | null>(null)
const actionDialog = reactive<{ visible: boolean; action: string; row: Row | null; 处理人: string; 解决轨迹: string; error: string }>({
  visible: false,
  action: '',
  row: null,
  处理人: '',
  解决轨迹: '',
  error: '',
})

function availableActions(row: Row): string[] {
  return STATUS_ACTIONS[String(row.status ?? row['处理状态'] ?? '')] ?? []
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  createFields.forEach((field) => { createForm[field.key] = '' })
  createError.value = ''
  createVisible.value = true
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('反馈详情读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '反馈详情读取失败'
  }
}

async function submitCreate() {
  createError.value = ''
  const missing = createFields.filter((field) => field.required && !createForm[field.key]?.trim())
  if (missing.length) {
    createError.value = `缺少必填字段：${missing.map((field) => field.label).join('、')}`
    return
  }
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload?.message || '反馈记录登记失败')
    }
    createVisible.value = false
    detail.value = payload.entry ?? null
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '反馈记录登记失败'
  }
}

function runAction(action: string, row: Row) {
  if (action === '开始处理') {
    void submitActionRequest(action, row, {})
    return
  }
  actionDialog.visible = true
  actionDialog.action = action
  actionDialog.row = row
  actionDialog.处理人 = String(row['处理人'] ?? '')
  actionDialog.解决轨迹 = String(row['解决轨迹'] ?? '')
  actionDialog.error = ''
}

async function submitAction() {
  const { action, row, 处理人, 解决轨迹 } = actionDialog
  if (!row) return
  if (action === '标记解决' && !解决轨迹.trim()) {
    actionDialog.error = '标记解决前必须填写解决轨迹'
    return
  }
  const ok = await submitActionRequest(action, row, { 处理人: 处理人.trim(), 解决轨迹: 解决轨迹.trim() })
  if (ok) {
    actionDialog.visible = false
  } else {
    actionDialog.error = errorMessage.value
  }
}

async function submitActionRequest(action: string, row: Row, extra: Record<string, string>): Promise<boolean> {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, ...extra } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload?.message || `数据质量反馈动作「${action}」未生效`)
    }
    await reload()
    return true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据质量反馈操作失败'
    return false
  }
}

async function fetchTotal(query: string): Promise<number> {
  const response = await request(`${ENDPOINT}?${query}&size=1`)
  if (!response.ok) return 0
  const payload = await response.json()
  return Number(payload.total ?? 0)
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('反馈记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    const [all, processing, resolved] = await Promise.all([
      fetchTotal(''),
      fetchTotal('status=处理中'),
      fetchTotal('status=已解决'),
    ])
    stats.value = [
      { label: '反馈记录总数', value: all },
      { label: '处理中反馈', value: processing },
      { label: '已解决反馈', value: resolved },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据质量反馈列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.muted-text { color: var(--muted); font-size: 12px; }
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.4); display: flex; align-items: center; justify-content: center; z-index: 20; }
.modal-card { background: #fff; border-radius: 10px; padding: 20px; width: 420px; max-width: 92vw; max-height: 86vh; overflow: auto; }
.modal-card h3 { margin: 0 0 14px; font-size: 15px; }
.form-item { display: block; margin-bottom: 10px; }
.form-item span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.form-item input, .form-item select, .form-item textarea { width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: 13px; font-family: inherit; }
.required-mark { color: #b42318; font-style: normal; margin-left: 2px; }
.modal-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 14px; }
.detail-grid { display: grid; grid-template-columns: 96px 1fr; gap: 8px 12px; margin: 0; font-size: 13px; }
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0; word-break: break-all; }
</style>
