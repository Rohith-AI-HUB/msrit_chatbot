export default function TypingIndicator() {
  return (
    <div className="flex items-end gap-2 px-4">
      {/* Bot avatar */}
      <div className="w-8 h-8 rounded-full bg-msrit-navy shrink-0 flex items-center
                      justify-center text-white text-xs font-bold">
        AI
      </div>

      {/* Bubble with bouncing dots */}
      <div className="bg-white rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm
                      border border-slate-100 flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-full bg-slate-400 animate-d0 inline-block" />
        <span className="w-2 h-2 rounded-full bg-slate-400 animate-d1 inline-block" />
        <span className="w-2 h-2 rounded-full bg-slate-400 animate-d2 inline-block" />
      </div>
    </div>
  )
}
