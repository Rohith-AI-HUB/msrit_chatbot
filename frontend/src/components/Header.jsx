import { SquarePen } from 'lucide-react'

export default function Header({ onNewChat }) {
  return (
    <header className="flex items-center justify-between px-5 py-3 bg-msrit-navy shadow-md shrink-0">
      {/* Left: logo + name */}
      <div className="flex items-center gap-3">
        {/* Simple circular logo placeholder */}
        <div className="w-9 h-9 rounded-full bg-msrit-gold flex items-center justify-center font-bold text-white text-sm select-none">
          RIT
        </div>
        <div>
          <p className="text-white font-semibold text-base leading-tight">
            MSRIT AI Assistant
          </p>
          <p className="text-blue-200 text-xs">
            Ramaiah Institute of Technology
          </p>
        </div>
      </div>

      {/* Right: new chat button */}
      <button
        onClick={onNewChat}
        title="New chat"
        className="flex items-center gap-1.5 text-sm text-blue-200 hover:text-white
                   hover:bg-white/10 px-3 py-1.5 rounded-lg transition-colors"
      >
        <SquarePen size={15} />
        <span className="hidden sm:inline">New Chat</span>
      </button>
    </header>
  )
}
