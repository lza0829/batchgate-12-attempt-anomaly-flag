<script setup>
import { onMounted, ref } from 'vue'
import { getJSON, patchJSON } from '../api'
const rows = ref([])
const msg = ref('')
const err = ref('')
async function refresh() { rows.value = await getJSON('/api/jobs') }
async function saveAttempts(row) {
  err.value = ''; msg.value = ''
  try {
    await patchJSON(`/api/jobs/${row.id}/max-attempts`, { max_attempts: Number(row.max_attempts) || 1 })
    msg.value = `已保存 ${row.name} 的 max_attempts`
    await refresh()
  } catch (e) { err.value = String(e.message || e) }
}
async function saveBaseline(row) {
  err.value = ''; msg.value = ''
  const hasMin = row.row_min !== null && row.row_min !== ''
  const hasMax = row.row_max !== null && row.row_max !== ''
  if (hasMin !== hasMax) {
    err.value = `${row.name}: row_min 与 row_max 必须同时设置或同时清空`
    return
  }
  try {
    await patchJSON(`/api/jobs/${row.id}/baseline`, {
      row_min: hasMin ? Number(row.row_min) : null,
      row_max: hasMax ? Number(row.row_max) : null,
      anomaly_policy: row.anomaly_policy,
    })
    msg.value = `已保存 ${row.name} 的行数基线`
    await refresh()
  } catch (e) { err.value = String(e.message || e) }
}
onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>作业</h1>
    <p class="muted">
      查看依赖、单次最大尝试次数与行数基线。成功尝试的行数落在 [row_min, row_max] 之外即标为异常；
      alert 保留水位并放行下游，block 保持旧水位并跳过下游。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <p v-if="msg" class="tag ok">{{ msg }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr><th>ID</th><th>名称</th><th>依赖</th><th>max_attempts</th><th>夹具</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="j in rows" :key="j.id">
            <td>{{ j.id }}</td>
            <td class="mono">{{ j.name }}</td>
            <td class="mono">{{ j.depends_on.join(', ') || '—' }}</td>
            <td><input type="number" min="1" max="10" v-model.number="j.max_attempts" style="width:4.5rem" /></td>
            <td class="mono">{{ j.fixture_path }}</td>
            <td><button class="secondary" @click="saveAttempts(j)">保存</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="panel">
      <h3>行数基线</h3>
      <p class="muted">留空即不标定。异常动作固定为 alert（告警放行）或 block（阻断下游）。</p>
      <table>
        <thead>
          <tr><th>作业</th><th>row_min</th><th>row_max</th><th>异常动作</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="j in rows" :key="j.id">
            <td class="mono">{{ j.name }}</td>
            <td><input type="number" min="0" v-model.number="j.row_min" style="width:5rem" placeholder="—" /></td>
            <td><input type="number" min="0" v-model.number="j.row_max" style="width:5rem" placeholder="—" /></td>
            <td>
              <select v-model="j.anomaly_policy">
                <option value="alert">alert · 告警放行</option>
                <option value="block">block · 阻断下游</option>
              </select>
            </td>
            <td><button class="secondary" @click="saveBaseline(j)">保存基线</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
