<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJSON } from '../api'
const route = useRoute()
const orchId = ref(null)
const anomalyOnly = ref(false)
const orchList = ref([])
const rows = ref([])
const err = ref('')
const exportUrl = computed(() => {
  const p = new URLSearchParams()
  if (orchId.value != null) p.set('orchestration_id', orchId.value)
  if (anomalyOnly.value) p.set('anomaly', 'true')
  const q = p.toString()
  return `/api/attempts/export${q ? `?${q}` : ''}`
})
async function load() {
  err.value = ''
  try {
    const p = new URLSearchParams()
    if (orchId.value != null) p.set('orchestration_id', orchId.value)
    if (anomalyOnly.value) p.set('anomaly', 'true')
    const q = p.toString()
    rows.value = await getJSON(`/api/attempts${q ? `?${q}` : ''}`)
  } catch (e) { err.value = String(e.message || e) }
}
onMounted(async () => {
  try {
    orchList.value = await getJSON('/api/orchestrations')
    const q = Number(route.query.orchestration_id)
    if (q) orchId.value = q
    await load()
  } catch (e) { err.value = String(e.message || e) }
})
watch([orchId, anomalyOnly], load)
</script>
<template>
  <div class="page">
    <h1>尝试记录</h1>
    <p class="muted">每次作业尝试的状态：success / failed / skipped_dep / skipped_anomaly。异常成功仍记 success，另带异常标记与原因。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <label>
        编排
        <select v-model.number="orchId">
          <option :value="null">全部</option>
          <option v-for="o in orchList" :key="o.id" :value="o.id">#{{ o.id }} · {{ o.status }}</option>
        </select>
      </label>
      <label style="margin-left:0.75rem">
        <input type="checkbox" v-model="anomalyOnly" />
        只看异常
      </label>
      <span class="muted" style="margin-left:0.75rem">共 {{ rows.length }} 条</span>
      <a :href="exportUrl" class="muted" style="margin-left:0.75rem">导出 JSONL →</a>
    </div>
    <div class="panel">
      <table>
        <thead>
          <tr><th>ID</th><th>编排</th><th>作业</th><th>次</th><th>状态</th><th>异常</th><th>详情</th></tr>
        </thead>
        <tbody>
          <tr v-for="a in rows" :key="a.id">
            <td>{{ a.id }}</td>
            <td>{{ a.orchestration_id }}</td>
            <td class="mono">{{ a.job_name }}</td>
            <td>{{ a.attempt_no }}</td>
            <td>
              <span class="tag" :class="a.status==='success'?'ok':(a.status==='failed'?'danger':'warn')">{{ a.status }}</span>
            </td>
            <td>
              <template v-if="a.is_anomaly">
                <span class="tag danger">{{ a.anomaly_policy }}</span>
                <span class="muted" style="margin-left:0.35rem">{{ a.consequence }}</span>
              </template>
              <span v-else class="muted">—</span>
            </td>
            <td class="mono">
              <div v-if="a.is_anomaly" class="tag warn">{{ a.anomaly_reason }}</div>
              <div>{{ JSON.stringify(a.detail) }}</div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
