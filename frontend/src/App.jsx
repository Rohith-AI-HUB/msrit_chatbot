import Header from './components/Header'
import ChatWindow from './components/ChatWindow'
import InputBar from './components/InputBar'
import { useChat } from './hooks/useChat'

export default function App() {
  const { messages, isLoading, sendMessage, setFeedback, clearChat } = useChat()

  return (
    <div className="flex flex-col h-full">
      <Header onNewChat={clearChat} />

      <ChatWindow
        messages={messages}
        isLoading={isLoading}
        setFeedback={setFeedback}
        onSuggest={sendMessage}
      />

      <InputBar onSend={sendMessage} isLoading={isLoading} />
    </div>
  )
}
