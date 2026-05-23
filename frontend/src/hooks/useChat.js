import { useState, useCallback } from 'react'
import { sendQuestion } from '../api/chat'

function makeId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function getOrCreateSessionId() {
  const key = 'msrit_session_id'
  let id = sessionStorage.getItem(key)
  if (!id) {
    id = `session-${Date.now()}`
    sessionStorage.setItem(key, id)
  }
  return id
}

export function useChat() {
  const [messages, setMessages] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId] = useState(getOrCreateSessionId)

  const sendMessage = useCallback(async (question) => {
    if (!question.trim() || isLoading) return

    // Add the user's message immediately
    const userMsg = { id: makeId(), role: 'user', content: question }
    setMessages(prev => [...prev, userMsg])
    setIsLoading(true)

    try {
      const data = await sendQuestion(question, sessionId)

      setMessages(prev => [...prev, {
        id: makeId(),
        role: 'assistant',
        content: data.answer,
        sources: data.sources ?? [],
        rewrittenQuery: data.rewritten_query ?? null,
        docCount: data.retrieved_documents_count ?? 0,
        feedback: null,   // 'up' | 'down' | null
        isError: false,
      }])
    } catch (err) {
      setMessages(prev => [...prev, {
        id: makeId(),
        role: 'assistant',
        content: `⚠️ Could not reach the backend. Make sure the server is running on port 8000.\n\n_${err.message}_`,
        sources: [],
        feedback: null,
        isError: true,
      }])
    } finally {
      setIsLoading(false)
    }
  }, [isLoading, sessionId])

  const setFeedback = useCallback((messageId, vote) => {
    setMessages(prev =>
      prev.map(m => m.id === messageId ? { ...m, feedback: vote } : m)
    )
  }, [])

  const clearChat = useCallback(() => {
    setMessages([])
    // New session on clear
    const newId = `session-${Date.now()}`
    sessionStorage.setItem('msrit_session_id', newId)
  }, [])

  return { messages, isLoading, sessionId, sendMessage, setFeedback, clearChat }
}
