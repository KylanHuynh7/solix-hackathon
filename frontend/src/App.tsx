import { useEffect, useState } from 'react'
import { USE_FIXTURES } from './api'
import { CaseDetail } from './views/CaseDetail'
import { CaseList } from './views/CaseList'

// Tiny hash router: "#/" is the case list, "#/cases/<id>" a case.
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

export default function App() {
  const [path, navigate] = useHashRoute()
  const caseMatch = path.match(/^\/cases\/(.+)$/)

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand" onClick={() => navigate('/')}>
          NeuroBiz
        </button>
        <span className="tagline">
          Agents propose · code verifies · a human approves · the ledger records
        </span>
        {USE_FIXTURES && <span className="badge badge-neutral">Fixture data</span>}
      </header>
      <main className="content">
        {caseMatch ? (
          <CaseDetail caseId={decodeURIComponent(caseMatch[1])} onBack={() => navigate('/')} />
        ) : (
          <CaseList onOpen={(id) => navigate(`/cases/${encodeURIComponent(id)}`)} />
        )}
      </main>
    </div>
  )
}
