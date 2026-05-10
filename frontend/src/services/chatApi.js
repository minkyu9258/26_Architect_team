const API_PREFIX = '/api/v1'

export async function createChatStream(message, sessionId = null) {
  const res = await fetch(`${API_PREFIX}/chat/streams`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  })
  if (!res.ok) throw new Error(`Stream create failed: ${res.status}`)
  return await res.json()
}
