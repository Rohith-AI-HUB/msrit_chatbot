import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ThumbsUp, ThumbsDown } from 'lucide-react'
import SourceList from './SourceList'

/** Renders bot answer using full Markdown — bullets, tables, code blocks, bold, etc. */
function MarkdownContent({ text }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        // Paragraphs
        p: ({ children }) => (
          <p className="text-sm text-slate-700 leading-relaxed mb-2 last:mb-0">{children}</p>
        ),
        // Headings
        h1: ({ children }) => (
          <h1 className="text-base font-bold text-slate-800 mt-3 mb-1">{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className="text-sm font-bold text-slate-800 mt-3 mb-1">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="text-sm font-semibold text-slate-700 mt-2 mb-1">{children}</h3>
        ),
        // Bullet / unordered list
        ul: ({ children }) => (
          <ul className="text-sm text-slate-700 space-y-1 my-2 pl-4 list-none">{children}</ul>
        ),
        // Ordered list
        ol: ({ children }) => (
          <ol className="text-sm text-slate-700 space-y-1 my-2 pl-4 list-decimal">{children}</ol>
        ),
        // List items
        li: ({ children }) => (
          <li className="flex gap-2 leading-relaxed">
            <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-msrit-blue shrink-0 flex-none" />
            <span className="flex-1 min-w-0">{children}</span>
          </li>
        ),
        // Bold
        strong: ({ children }) => (
          <strong className="font-semibold text-slate-800">{children}</strong>
        ),
        // Italic
        em: ({ children }) => (
          <em className="italic text-slate-600">{children}</em>
        ),
        // Inline code
        code: ({ inline, children }) =>
          inline ? (
            <code className="bg-slate-100 text-msrit-blue text-xs px-1.5 py-0.5 rounded font-mono">
              {children}
            </code>
          ) : (
            <code className="block bg-slate-900 text-green-300 text-xs font-mono
                            p-3 rounded-lg overflow-x-auto whitespace-pre my-2">
              {children}
            </code>
          ),
        // Code block wrapper
        pre: ({ children }) => (
          <pre className="bg-slate-900 rounded-lg overflow-x-auto my-2">{children}</pre>
        ),
        // Blockquote
        blockquote: ({ children }) => (
          <blockquote className="border-l-3 border-msrit-blue pl-3 italic text-slate-500 my-2 text-sm">
            {children}
          </blockquote>
        ),
        // Horizontal rule
        hr: () => <hr className="border-slate-200 my-3" />,
        // Tables (remark-gfm)
        table: ({ children }) => (
          <div className="overflow-x-auto my-3">
            <table className="w-full text-xs border-collapse">{children}</table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-msrit-navy text-white">{children}</thead>
        ),
        tbody: ({ children }) => (
          <tbody className="divide-y divide-slate-100">{children}</tbody>
        ),
        tr: ({ children }) => <tr className="even:bg-slate-50">{children}</tr>,
        th: ({ children }) => (
          <th className="text-left px-3 py-2 font-semibold text-xs">{children}</th>
        ),
        td: ({ children }) => (
          <td className="px-3 py-2 text-slate-700">{children}</td>
        ),
        // Links
        a: ({ href, children }) => (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-msrit-blue hover:underline"
          >
            {children}
          </a>
        ),
      }}
    >
      {text}
    </ReactMarkdown>
  )
}

function BotMessage({ msg, onFeedback }) {
  return (
    <div className="flex items-start gap-2.5">
      {/* Avatar */}
      <div className="w-7 h-7 rounded-full bg-msrit-navy shrink-0 flex items-center
                      justify-center text-white text-[10px] font-bold mt-0.5">
        AI
      </div>

      {/* Bubble */}
      <div className={`flex-1 min-w-0 bg-white rounded-2xl rounded-tl-sm shadow-sm
                       border px-4 py-3
                       ${msg.isError ? 'border-red-200 bg-red-50' : 'border-slate-100'}`}>

        <MarkdownContent text={msg.content} />

        {/* Rewritten query hint */}
        {msg.rewrittenQuery && msg.rewrittenQuery !== msg.content && (
          <p className="text-xs text-slate-400 italic mt-2">
            Searched as: &ldquo;{msg.rewrittenQuery}&rdquo;
          </p>
        )}

        {/* Sources */}
        {msg.sources && msg.sources.length > 0 && (
          <div className="mt-3 pt-2 border-t border-slate-100">
            <SourceList sources={msg.sources} />
          </div>
        )}

        {/* Feedback */}
        {!msg.isError && (
          <div className="flex items-center gap-2 mt-2 pt-2 border-t border-slate-100">
            <span className="text-xs text-slate-400">Helpful?</span>
            <button
              onClick={() => onFeedback(msg.id, 'up')}
              className={`p-1 rounded transition-colors
                ${msg.feedback === 'up'
                  ? 'text-green-600 bg-green-50'
                  : 'text-slate-400 hover:text-green-600 hover:bg-green-50'}`}
            >
              <ThumbsUp size={13} />
            </button>
            <button
              onClick={() => onFeedback(msg.id, 'down')}
              className={`p-1 rounded transition-colors
                ${msg.feedback === 'down'
                  ? 'text-red-500 bg-red-50'
                  : 'text-slate-400 hover:text-red-500 hover:bg-red-50'}`}
            >
              <ThumbsDown size={13} />
            </button>
            {msg.feedback && (
              <span className="text-xs text-slate-400 ml-1">
                {msg.feedback === 'up' ? 'Thanks!' : "We'll improve."}
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
                      px-4 py-2.5 text-sm leading-relaxed shadow-sm whitespace-pre-wrap">
        {msg.content}
      </div>
    </div>
  )
}

export default function Message({ msg, onFeedback }) {
  if (msg.role === 'user') return <UserMessage msg={msg} />
  return <BotMessage msg={msg} onFeedback={onFeedback} />
}
