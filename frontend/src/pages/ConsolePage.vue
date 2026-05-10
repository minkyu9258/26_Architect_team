<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import ChatComposer from '@/components/chat/ChatComposer.vue'
import { createChatStream } from '@/services/chatApi'
import StreamStatus from '@/stream_view/StreamStatus.vue'
import { createStreamConnection } from '@/stream_view/services/eventSourceClient'

const isLoading = ref(false)
const error = ref('')
const status = ref('idle')
const events = ref([])
const sessionId = ref('')
const intent = ref('')
const routeSource = ref('')
const planner = ref(null)
const ragHits = ref([])
const taskCount = ref(0)
const resultCount = ref(0)
const turns = ref([])
const chatWindowEl = ref(null)
let connection = null

const topCards = computed(() => [
  { label: 'Session', value: sessionId.value || '(none)' },
  { label: 'Intent', value: intent.value || '(pending)' },
  { label: 'Route', value: routeSource.value || '(pending)' },
  { label: 'Events', value: String(events.value.length) },
  { label: 'Planned Tasks', value: String(taskCount.value) },
  { label: 'Agent Results', value: String(resultCount.value) },
])

const routeBadgeLabel = computed(() => {
  const route = routeSource.value.toLowerCase()
  const hasRag = ragHits.value.length > 0
  const isGeneral = intent.value.toLowerCase() === 'general'

  if (!route && !hasRag) return 'Pending'
  if ((route.includes('llm') || route === 'hitl') && isGeneral && !hasRag) return 'LLM General'
  if ((route.includes('llm') || route === 'hitl') && isGeneral && hasRag) return 'LLM General+RAG'
  if ((route.includes('llm') || route === 'hitl') && hasRag) return 'LLM+RAG'
  if (route.includes('llm') || route === 'hitl') return 'LLM'
  if (route.includes('rule') && hasRag) return 'RULE+RAG'
  if (route.includes('rule')) return 'RULE'
  if (hasRag) return 'RAG'
  return routeSource.value || 'Pending'
})

const routeBadgeClass = computed(() => {
  const label = routeBadgeLabel.value
  if (label.includes('LLM')) return 'is-llm'
  if (label.includes('RULE')) return 'is-rule'
  if (label.includes('RAG')) return 'is-rag'
  return 'is-pending'
})

function closeStream() {
  if (!connection) return
  connection.close()
  connection = null
}

function addTurn(role, text, meta = '', evidence = []) {
  turns.value.push({ role, text, meta, evidence, at: new Date().toISOString() })
}

function getTurnRouteLabel(turn) {
  const meta = String(turn.meta || '').toLowerCase()
  const hasRag = Array.isArray(turn.evidence) && turn.evidence.length > 0
  const isGeneral = meta.includes('general')

  if ((meta.includes('llm') || meta.includes('hitl')) && isGeneral && !hasRag) return 'LLM General'
  if ((meta.includes('llm') || meta.includes('hitl')) && isGeneral && hasRag) return 'LLM General+RAG'
  if ((meta.includes('llm') || meta.includes('hitl')) && hasRag) return 'LLM+RAG'
  if (meta.includes('llm') || meta.includes('hitl')) return 'LLM'
  if (meta.includes('rule') && hasRag) return 'RULE+RAG'
  if (meta.includes('rule')) return 'RULE'
  if (hasRag) return 'RAG'
  return turn.meta || ''
}

function newChat() {
  closeStream()
  error.value = ''
  status.value = 'idle'
  events.value = []
  sessionId.value = ''
  intent.value = ''
  routeSource.value = ''
  planner.value = null
  ragHits.value = []
  taskCount.value = 0
  resultCount.value = 0
  turns.value = []
}

function parseEvent(event) {
  try {
    return JSON.parse(event.data)
  } catch {
    return { raw: event.data }
  }
}

async function handleSend(message) {
  if (isLoading.value) return

  isLoading.value = true
  error.value = ''
  status.value = 'connecting'
  events.value = []
  planner.value = null
  ragHits.value = []
  taskCount.value = 0
  resultCount.value = 0

  addTurn('user', message)

  try {
    const streamInfo = await createChatStream(message, sessionId.value || null)
    sessionId.value = streamInfo.session_id

    closeStream()
    connection = createStreamConnection(streamInfo.stream_url, {
      onOpen: () => {
        status.value = 'connected'
      },
      onEvent: (event) => {
        const parsed = parseEvent(event)
        events.value = [{ type: event.type, data: parsed }, ...events.value].slice(0, 30)

        if (parsed.intent) intent.value = parsed.intent
        if (parsed.route_source) routeSource.value = parsed.route_source
        if (event.type === 'planning' && Array.isArray(parsed.tasks)) taskCount.value = parsed.tasks.length
        if (event.type === 'progress' && parsed.phase === 'planner_completed') planner.value = parsed.plan || null
        if (parsed.routing_debug?.rag?.hits) ragHits.value = parsed.routing_debug.rag.hits
        if (event.type === 'result') resultCount.value += 1

        if (event.type === 'progress' && parsed.message) {
          addTurn('system', parsed.message, parsed.phase || 'progress')
        }

        if (event.type === 'final') {
          const finalText = parsed.clarification_question || parsed.summary || 'Done'
          const evidence = parsed.routing_debug?.rag?.hits || []
          addTurn('assistant', finalText, `${parsed.intent || ''} / ${parsed.route_source || ''}`, evidence)
          status.value = 'done'
          isLoading.value = false
          closeStream()
        }

        if (event.type === 'error') {
          error.value = parsed.message || 'Stream error'
          addTurn('assistant', error.value, 'error')
          status.value = 'error'
          isLoading.value = false
          closeStream()
        }
      },
      onError: () => {
        status.value = 'error'
        error.value = 'SSE connection failed'
        addTurn('assistant', error.value, 'error')
        isLoading.value = false
        closeStream()
      },
    })
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Unknown error'
    addTurn('assistant', error.value, 'error')
    status.value = 'error'
    isLoading.value = false
  }
}

watch(
  () => turns.value.length,
  async () => {
    await nextTick()
    if (chatWindowEl.value) {
      chatWindowEl.value.scrollTop = chatWindowEl.value.scrollHeight
    }
  },
)

onBeforeUnmount(closeStream)
</script>

<template>
  <main class="console-shell">
    <section class="console-panel">
      <div class="console-heading">
        <p class="eyebrow">AI Agent Orchestrator</p>
        <h1>Enterprise Console</h1>
        <p class="route-badge" :class="routeBadgeClass">{{ routeBadgeLabel }}</p>
      </div>

      <div class="card-grid">
        <article v-for="item in topCards" :key="item.label" class="stat-card">
          <p class="stat-label">{{ item.label }}</p>
          <p class="stat-value">{{ item.value }}</p>
        </article>
      </div>

      <div class="console-grid">
        <div class="chat-column">
          <section ref="chatWindowEl" class="chat-window">
            <p v-if="turns.length === 0" class="summary">아직 대화가 없습니다. 아래 입력창에서 명령을 실행하세요.</p>
            <div v-for="(turn, idx) in turns" :key="idx" class="bubble-row" :class="`role-${turn.role}`">
              <div class="bubble">
                <p class="bubble-text">{{ turn.text }}</p>
                <p v-if="turn.meta" class="bubble-meta">
                  <span class="inline-route-badge">{{ getTurnRouteLabel(turn) }}</span>
                </p>
                <ul v-if="turn.evidence && turn.evidence.length" class="bubble-evidence">
                  <li v-for="(hit, hIdx) in turn.evidence" :key="`${hIdx}-${hit.doc_key}`">
                    {{ hit.doc_key }} ({{ Number(hit.score || 0).toFixed(3) }})
                  </li>
                </ul>
              </div>
            </div>
          </section>

          <section class="composer-dock">
            <ChatComposer :is-loading="isLoading" @send="handleSend" @new-chat="newChat" />
          </section>

          <section class="plan-panel" v-if="planner">
            <h2>Planner Output</h2>
            <pre>{{ planner }}</pre>
          </section>

          <section class="plan-panel" v-if="ragHits.length">
            <h2>RAG Evidence</h2>
            <ul class="rag-list">
              <li v-for="(hit, idx) in ragHits" :key="`${hit.doc_key}-${idx}`">
                <strong>{{ hit.doc_key }}</strong>
                <span>score={{ Number(hit.score || 0).toFixed(4) }}</span>
                <span>source={{ hit.metadata?.source || 'unknown' }}</span>
              </li>
            </ul>
          </section>
        </div>

        <StreamStatus :status="status" :events="events" />
      </div>
    </section>
  </main>
</template>
