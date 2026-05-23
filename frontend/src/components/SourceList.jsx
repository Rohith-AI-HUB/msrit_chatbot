import { ExternalLink } from 'lucide-react'

function shortenUrl(url) {
  try {
    const u = new URL(url)
    // show just the pathname, strip leading slash
    const path = u.pathname.replace(/^\//, '').replace(/\.html$/, '') || u.hostname
    return path || url
  } catch {
    return url
  }
}

export default function SourceList({ sources }) {
  if (!sources || sources.length === 0) return null

  return (
    <div className="mt-2">
      <p className="text-xs text-slate-400 mb-1 font-medium uppercase tracking-wide">
        Sources
      </p>
      <div className="flex flex-wrap gap-1.5">
        {sources.map((src) => (
          <a
            key={src}
            href={src}
            target="_blank"
            rel="noopener noreferrer"
            title={src}
            className="flex items-center gap-1 text-xs bg-slate-100 hover:bg-msrit-navy
                       hover:text-white text-slate-600 border border-slate-200
                       rounded-full px-2.5 py-1 transition-colors max-w-[200px] truncate"
          >
            <ExternalLink size={10} className="shrink-0" />
            <span className="truncate">{shortenUrl(src)}</span>
          </a>
        ))}
      </div>
    </div>
  )
}
