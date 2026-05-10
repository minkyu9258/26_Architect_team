<script setup>
import { ref } from 'vue'

defineProps({
  isLoading: { type: Boolean, default: false },
})

const emit = defineEmits({
  send: (message) => typeof message === 'string' && message.trim().length > 0,
  newChat: () => true,
})

const message = ref('')

function submit() {
  const value = message.value.trim()
  if (!value) return
  emit('send', value)
  message.value = ''
}
</script>

<template>
  <form class="chat-form" @submit.prevent="submit">
    <label for="message">AI Command</label>
    <textarea
      id="message"
      v-model="message"
      rows="6"
      placeholder="Jira와 GitHub 프로젝트 기본 셋업해줘"
      @keydown.enter.exact.prevent="submit"
    />
    <div class="row-actions">
      <button type="submit" :disabled="isLoading || !message.trim()">{{ isLoading ? 'Running...' : 'Run' }}</button>
      <button type="button" class="secondary-button" :disabled="isLoading" @click="emit('newChat')">새 대화</button>
    </div>
  </form>
</template>
