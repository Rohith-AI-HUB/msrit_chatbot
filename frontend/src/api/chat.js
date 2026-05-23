const API_BASE = '/api'

/**
 * Send a question to the MSRIT chatbot backend.
 *
 * @param {string} question
 * @param {string} sessionId
 * @returns {Promise<{
 *   answer: string,
 *   sources: string[],
 *   rewritten_query: string,
 *   retrieved_documents_count: number
 * }>}
 */
export async function sendQuestion(question, sessionId) {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, session_id: sessionId, debug: false }),
  })

  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Server error ${res.status}: ${text}`)
  }

  return res.json()
}
