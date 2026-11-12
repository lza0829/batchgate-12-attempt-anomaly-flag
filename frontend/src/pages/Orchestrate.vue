<script setup>
import { onMounted, ref } from 'vue'
import { getJSON, postJSON } from '../api'
const history = ref([])
const last = ref(null)
const busy = ref(false)
const err = ref('')
async function refresh() { history.value = await getJSON('/api/orchestrations') }
async function runOnce() {
  err.value = ''; busy.value = true
  try {
    last.value = await postJSON('/api/orchestrations')
    await refresh()
  } catch (e) { err.value = String(e.message || e) }
  finally { busy.value = false }
}
onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>编排台</h1>
    <p class="muted">触发一次全图编排：按依赖层执行；上游未成功记 skipped_dep，上游异常且策略为 block 则记 skipped_anomaly。</p>
    <div class="panel">
      <button :disabled="busy" @click="runOnce">{{ busy ? '编排中…' : '执行编排' }}</button>
    </div>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel" v-if="last">
      <h3>最近一次报告</h3>
      <p>
        #{{ last.id }} ·
        <span class="tag" :class="last.status==='ok'?'ok':'warn'">{{ last.status }}</span> ·
        succeeded {{ last.report?.succeeded }}（正常 {{ last.report?.normal_success }}） /
        failed {{ last.report?.failed }} /
        skipped {{ last.report?.skipped }}（因异常 {{ last.report?.skipped_anomaly }}） /
        attempts {{ last.report?.attempt_count }}
      </p>
      <p>
        <span class="tag danger">异常 {{ last.report?.anomaly_count }}</span>
        <span class="muted" style="margin-left:0.5rem">
          alert {{ last.report?.anomaly_alert }} · block {{ last.report?.anomaly_block }}
        </span>
      </p>
      <p class="mono muted">watermarked_jobs={{ last.report?.watermarked_jobs }} layers={{ last.report?.layer_count }}</p>
      <p>
        <router-link :to="{ path: '/attempts', query: { orchestration_id: last.id } }">查看本次尝试 →</router-link>
        ·
        <router-link to="/watermarks">产出水位 →</router-link>
      </p>
    </div>
    <div class="panel">
      <h3>历史编排</h3>
      <table>
        <thead><tr><th>ID</th><th>状态</th><th>成功</th><th>失败</th><th>跳过</th><th>异常</th><th>开始</th></tr></thead>
        <tbody>
          <tr v-for="o in history" :key="o.id">
            <td>{{ o.id }}</td>
            <td>{{ o.status }}</td>
            <td>{{ o.report?.succeeded }}</td>
            <td>{{ o.report?.failed }}</td>
            <td>{{ o.report?.skipped }}</td>
            <td>{{ o.report?.anomaly_count ?? 0 }}</td>
            <td class="mono">{{ o.started_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
