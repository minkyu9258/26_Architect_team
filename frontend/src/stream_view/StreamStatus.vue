<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: String, default: 'idle' },
  events: { type: Array, default: () => [] },
})

const stages = [
  { key: 'intent_analyzing', label: 'Intent Analyzing' },
  { key: 'intent_resolved', label: 'Intent Resolved' },
  { key: 'planning', label: 'Planning' },
  { key: 'result', label: 'Agent Execution' },
  { key: 'final', label: 'Finalized' },
]

const normalizedEvents = computed(() => {
  return props.events.map((e) => {
    const data = e?.data || {}
    if (e.type === 'progress' && data.phase) {
      return { key: data.phase, label: String(data.phase).replaceAll('_', ' '), type: e.type, data }
    }
    return { key: e.type, label: e.type, type: e.type, data }
  })
})

const currentStepIndex = computed(() => {
  const keys = new Set(normalizedEvents.value.map((e) => e.key))
  let idx = -1
  if (keys.has('intent_analyzing')) idx = 0
  if (keys.has('intent_resolved')) idx = 1
  if (keys.has('planning')) idx = 2
  if (keys.has('result')) idx = 3
  if (keys.has('final')) idx = 4
  return idx
})
</script>

<template>
  <aside class="stream-panel">
    <div>
      <p class="panel-label">SSE EventSource</p>
      <h2>Stream Timeline</h2>
    </div>

    <p class="stream-state" :data-state="status">{{ status }}</p>

    <ol class="stepper">
      <li
        v-for="(stage, idx) in stages"
        :key="stage.key"
        :class="{ done: idx <= currentStepIndex, current: idx === currentStepIndex }"
      >
        <span class="dot" />
        <span class="txt">{{ stage.label }}</span>
      </li>
    </ol>

    <ul v-if="events.length" class="event-list">
      <li v-for="(entry, idx) in events" :key="idx">
        <strong>{{ entry.type }}</strong>
        <pre>{{ entry.data }}</pre>
      </li>
    </ul>

    <p v-else class="summary">No stream events yet.</p>
  </aside>
</template>
