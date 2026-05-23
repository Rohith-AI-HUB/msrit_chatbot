import { useEffect, useRef } from 'react'
import Message from './Message'
import TypingIndicator from './TypingIndicator'
import WelcomeScreen from './WelcomeScreen'

export default function ChatWindow({ messages, isLoading, setFeedback, onSuggest }) {
  const bottomRef = useRef(null)

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  if (messages.length === 0 && !isLoading) {
    return (
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        <WelcomeScreen onSuggest={onSuggest} />
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-5">
      <div className="max-w-3xl mx-auto space-y-5">
        {messages.map(msg => (
          <Message
            key={msg.id}
            msg={msg}
            onFeedback={setFeedback}
          />
        ))}

        {isLoading && <TypingIndicator />}

        <div ref={bottomRef} />
      </div>
    </div>
  )
}
