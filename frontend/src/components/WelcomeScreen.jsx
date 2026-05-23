const SUGGESTIONS = [
  'What are the admission requirements for B.E.?',
  'Tell me about placement statistics at MSRIT.',
  'What departments does MSRIT offer?',
  'What are the hostel facilities like?',
]

export default function WelcomeScreen({ onSuggest }) {
  return (
    <div className="flex flex-col items-center justify-center h-full px-4 text-center gap-6">
      {/* Icon */}
      <div className="w-16 h-16 rounded-2xl bg-msrit-navy flex items-center justify-center shadow-lg">
        <span className="text-3xl">🎓</span>
      </div>

      {/* Title */}
      <div>
        <h1 className="text-2xl font-bold text-msrit-navy">
          Hello! I'm your MSRIT Assistant
        </h1>
        <p className="mt-1 text-slate-500 text-sm max-w-sm">
          Ask me anything about admissions, departments, placements,
          facilities, and more.
        </p>
      </div>

      {/* Suggestion chips */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onSuggest(s)}
            className="text-left text-sm text-slate-600 bg-white hover:bg-msrit-navy
                       hover:text-white border border-slate-200 rounded-xl px-4 py-3
                       transition-colors shadow-sm"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}
