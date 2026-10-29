import { useEffect, useState } from 'react'
import { listDrafts, USE_FIXTURES } from './api'
import { DemoBar } from './components/DemoBar'
import { SessionProvider, useLoad } from './session'
import { AuditView } from './views/AuditView'
import { CaseDetail } from './views/CaseDetail'
import { CaseList } from './views/CaseList'
import { ReviewQueue } from './views/ReviewQueue'

// Tiny hash router: "#/" cases, "#/cases/<id>", "#/review", "#/audit".
function readHash(): string {
  return window.location.hash.replace(/^#/, '') || '/'
}

function useHashRoute(): [string, (path: string) => void] {
  const [path, setPath] = useState(readHash)
  useEffect(() => {
    const onChange = () => setPath(readHash())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return [path, (next) => (window.location.hash = next)]
}

function Nav({ path, navigate }: { path: string; navigate: (p: string) => void }) {
  const [drafts] = useLoad(() => listDrafts())
  const waiting = drafts?.filter((d) => d.status === 'proposed').length ?? 0
  const items: [string, string, boolean][] = [
    ['/', 'Cases', path === '/' || path.startsWith('/cases/')],
    ['/review', 'Review queue', path === '/review'],
    ['/audit', 'Audit', path === '/audit'],
  ]
  return (
    <nav className="nav">
      {items.map(([to, label, active]) => (
        <button
          key={to}
          className={`nav-item ${active ? 'nav-active' : ''}`}
          onClick={() => navigate(to)}
        >
          {label}
          {to === '/review' && waiting > 0 && <span className="nav-count">{waiting}</span>}
        </button>
      ))}
    </nav>
  )
}

export default function App() {
  const [path, navigate] = useHashRoute()
  const caseMatch = path.match(/^\/cases\/(.+)$/)

  let page
  if (caseMatch) {
    page = <CaseDetail caseId={decodeURIComponent(caseMatch[1])} onBack={() => navigate('/')} />
  } else if (path === '/review') {
    page = <ReviewQueue />
  } else if (path === '/audit') {
    page = <AuditView />
  } else {
    page = <CaseList onOpen={(id) => navigate(`/cases/${encodeURIComponent(id)}`)} />
  }

  return (
    <SessionProvider>
      <div className="app">
        <header className="topbar">
          <button className="brand" onClick={() => navigate('/')}>
            TransPharmic
          </button>
          <Nav path={path} navigate={navigate} />
          <span className="tagline">
            Agents propose · code verifies · a human approves · the ledger records
          </span>
          {USE_FIXTURES && <span className="badge badge-neutral">Fixture data</span>}
        </header>
        <DemoBar />
        <main className="content">{page}</main>
      </div>
    </SessionProvider>
  )
}
