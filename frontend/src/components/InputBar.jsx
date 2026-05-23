import { useRef, useState, useEffect } from 'react'
import { Send, Mic, MicOff, Square } from 'lucide-react'

export default function InputBar({ onSend, isLoading }) {
  const [text, setText] = useState('')
  const [listening, setListening] = useState(false)
  const textareaRef = useRef(null)
  const recognitionRef = useRef(null)

  // Auto-grow textarea
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`
  }, [text])

  // Voice input via Web Speech API
  function toggleMic() {
    if (!('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)) {
      alert('Voice input is not supported in this browser. Try Chrome.')
      return
    }

    if (listening) {
      recognitionRef.current?.stop()
      setListening(false)
      return
    }

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    const rec = new SR()
    rec.lang = 'en-IN'
    rec.continuous = false
    rec.interimResults = false

    rec.onresult = (e) => {
      const transcript = e.results[0][0].transcript
      setText(prev => prev ? `${prev} ${transcript}` : transcript)
    }
    rec.onerror = () => setListening(false)
    rec.onend  = () => setListening(false)

    rec.start()
    recognitionRef.current = rec
    setListening(true)
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function submit() {
    const q = text.trim()
    if (!q || isLoading) return
    onSend(q)
    setText('')
  }

  const canSend = text.trim().length > 0 && !isLoading

  return (
    <div className="shrink-0 px-4 py-3 bg-white border-t border-slate-200">
      <div className="max-w-3xl mx-auto flex items-end gap-2">

        {/* Voice button */}
        <button
          onClick={toggleMic}
          title={listening ? 'Stop listening' : 'Voice input'}
          className={`shrink-0 w-10 h-10 rounded-xl flex items-center justify-center
                      transition-colors
                      ${listening
                        ? 'bg-red-100 text-red-500 hover:bg-red-200'
                        : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                      }`}
        >
          {listening ? <Square size={16} /> : <Mic size={16} />}
        </button>

        {/* Text area */}
        <div className="flex-1 flex items-end bg-slate-100 rounded-2xl px-3 py-2
                        border border-transparent focus-within:border-msrit-blue
                        focus-within:bg-white transition-colors">
          <textarea
            ref={textareaRef}
            rows={1}
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={listening ? '🎙 Listening…' : 'Ask anything about MSRIT…'}
            disabled={isLoading}
            className="flex-1 bg-transparent resize-none outline-none text-sm
                       text-slate-800 placeholder-slate-400 leading-relaxed
                       disabled:opacity-50"
          />
        </div>

        {/* Send button */}
        <button
          onClick={submit}
          disabled={!canSend}
          title="Send"
          className={`shrink-0 w-10 h-10 rounded-xl flex items-center justify-center
                      transition-colors
                      ${canSend
                        ? 'bg-msrit-navy text-white hover:bg-msrit-blue'
                        : 'bg-slate-200 text-slate-400 cursor-not-allowed'
                      }`}
        >
          <Send size={16} />
        </button>
      </div>

      <p className="text-center text-xs text-slate-400 mt-1.5">
        Press <kbd className="px-1 py-0.5 bg-slate-100 rounded text-[10px]">Enter</kbd> to send
        &nbsp;·&nbsp;
        <kbd className="px-1 py-0.5 bg-slate-100 rounded text-[10px]">Shift+Enter</kbd> for new line
      </p>
    </div>
  )
}
