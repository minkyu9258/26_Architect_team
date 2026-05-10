export function createStreamConnection(url, { onOpen, onEvent, onError } = {}) {
  const es = new EventSource(url)
  es.onopen = onOpen || null
  es.onerror = onError || null

  es.onmessage = (evt) => {
    onEvent && onEvent({ type: 'message', data: evt.data })
  }

  ;['progress', 'planning', 'result', 'final', 'error'].forEach((eventName) => {
    es.addEventListener(eventName, (evt) => {
      onEvent && onEvent({ type: eventName, data: evt.data })
    })
  })

  return es
}
