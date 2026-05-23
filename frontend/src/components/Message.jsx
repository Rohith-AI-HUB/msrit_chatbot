import { ThumbsUp, ThumbsDown } from 'lucide-react'
import SourceList from './SourceList'

/** Render bot answer text — preserves newlines and bolds **text** */
function FormattedText({ text }) {
  const lines = text.split('\n')
  return (
    <div className="text-sm text-slate-700 leading-relaxed space-y-1">
      {lines.map((line, i) => {
        // Bold: **text**
        const parts = line.split(/(\*\*[^*]+\*\*)/g)
        return (
          <p key={i} className={line === '' ? 'h-2' : ''}>
            {parts.map((part, j) =>
              part.startsWith('**') && part.endsWith('**')
                ? <strong key={j}>{part.slice(2, -2)}</strong>
                : part
            )}
          </p>
        )
      })}
    </div>
  )
}

function BotMessage({ msg, onFeedback }) {
  return (
    <div className="flex items-end gap-2">
      {/* Avatar */}
      <div className="w-8 h-8 rounded-full bg-msrit-navy shrink-0 flex items-center
                      justify-center text-white text-xs font-bold self-start mt-1">
        AI
      </div>

      {/* Bubble */}
      <div className={`max-w-[80%] bg-white rounded-2xl rounded-bl-sm shadow-sm
                       border px-4 py-3 space-y-2
                       ${msg.isError ? 'border-red-200 bg-red-50' : 'border-slate-100'}`}>

        <FormattedText text={msg.content} />

        {/* Rewritten query hint */}
        {msg.rewrittenQuery && msg.rewrittenQuery !== msg.content && (
          <p className="text-xs text-slate-400 italic">
            Searched as: "{msg.rewrittenQuery}"
          </p>
        )}

        {/* Doc count badge */}
        {msg.docCount > 0 && (
          <span className="inline-block text-xs text-slate-400">
            {msg.docCount} source{msg.docCount !== 1 ? 's' : ''} used
          </span>
        )}

        <SourceList sources={msg.sources} />

        {/* Feedback */}
        {!msg.isError && (
          <div className="flex items-center gap-2 pt-1 border-t border-slate-100">
            <span className="text-xs text-slate-400 mr-1">Was this helpful?</span>
            <button
              onClick={() => onFeedback(msg.id, 'up')}
              title="Helpful"
              className={`p-1 rounded-md transition-colors
                ${msg.feedback === 'up'
                  ? 'text-green-600 bg-green-50'
                  : 'text-slate-400 hover:text-green-600 hover:bg-green-50'
                }`}
            >
              <ThumbsUp size={14} />
            </button>
            <button
              onClick={() => onFeedback(msg.id, 'down')}
              title="Not helpful"
              className={`p-1 rounded-md transition-colors
                ${msg.feedback === 'down'
                  ? 'text-red-500 bg-red-50'
                  : 'text-slate-400 hover:text-red-500 hover:bg-red-50'
                }`}
            >
              <ThumbsDown size={14} />
            </button>
            {msg.feedback && (
              <span className="text-xs text-slate-400 ml-1">
                {msg.feedback === 'up' ? 'Thanks for the feedback!' : 'We\'ll improve this.'}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function UserMessage({ msg }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[75%] bg-msrit-blue text-white rounded-2xl rounded-br-sm
                      px-4 py-2.5 text-sm leading-relaxed shadow-sm">
        {msg.content}
      </div>
    </div>
  )
}

export default function Message({ msg, onFeedback }) {
  if (msg.role === 'user') return <UserMessage msg={msg} />
  return <BotMessage msg={msg} onFeedback={onFeedback} />
}
