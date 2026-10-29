import { useEffect, useState } from 'react'
import { listDrafts, USE_FIXTURES } from './api'
import { DemoBar } from './components/DemoBar'
import { Icon, LogoMark, type IconName } from './components/Icon'
import { SessionProvider, useApprover, useLoad } from './session'
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

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')
}

function Sidebar({ path, navigate }: { path: string; navigate: (p: string) => void }) {
  const [drafts] = useLoad(() => listDrafts())
  const { approver } = useApprover()
  const waiting = drafts?.filter((d) => d.status === 'proposed').length ?? 0
  const items: { to: string; label: string; icon: IconName; active: boolean; count?: number }[] = [
    { to: '/', label: 'Cases', icon: 'cases', active: path === '/' || path.startsWith('/cases/') },
    { to: '/review', label: 'Review queue', icon: 'review', active: path === '/review', count: waiting },
    { to: '/audit', label: 'Audit trail', icon: 'audit', active: path === '/audit' },
  ]

  return (
    <aside className="sidebar">
      <button className="brand" onClick={() => navigate('/')} aria-label="Transpharmic home">
        <LogoMark size={34} />
        <span className="wordmark">Transpharmic</span>
      </button>

      <div className="side-label">Procurement</div>
      <nav className="nav" aria-label="Main">
        {items.map((item) => (
          <button
            key={item.to}
            className={`nav-item ${item.active ? 'nav-active' : ''}`}
            aria-current={item.active ? 'page' : undefined}
            onClick={() => navigate(item.to)}
          >
            <Icon name={item.icon} />
            <span>{item.label}</span>
            {item.count ? <span className="nav-count">{item.count}</span> : null}
          </button>
        ))}
      </nav>

      <div className="side-foot">
        <div className="side-label">Every action</div>
        <ol className="principles">
          <li>Agents propose</li>
          <li>Code verifies</li>
          <li>A human approves</li>
          <li>The ledger records</li>
        </ol>
        {USE_FIXTURES && <span className="badge badge-neutral fixture-badge">Fixture data</span>}
        <div className="operator">
          <span className="avatar">{approver ? initials(approver) : <Icon name="user" size={16} />}</span>
          <span>
            <span className="operator-label">Approver</span>
            <span className="operator-name">{approver || 'Set on first approval'}</span>
          </span>
        </div>
      </div>
    </aside>
  )
}

const PAGES: Record<string, { title: string; sub: string }> = {
  '/': { title: 'Cases', sub: 'Every sourcing request, its supplier offers and where it stands.' },
  '/review': {
    title: 'Review queue',
    sub: 'Agents draft every email. Nothing is sent until a person approves it.',
  },
  '/audit': {
    title: 'Audit trail',
    sub: 'Every read, check, draft and approval, append-only and hash-chained.',
  },
}

function PageHeader({ path, caseId, navigate }: { path: string; caseId: string | null; navigate: (p: string) => void }) {
  const page = caseId
    ? { title: caseId, sub: 'Supplier offers with their source evidence, checks and SAP documents.' }
    : (PAGES[path] ?? PAGES['/'])
  return (
    <header className="pagehead">
      <div>
        <div className="crumbs">
          <span>Transpharmic</span>
          <Icon name="chevron" size={14} />
          {caseId ? (
            <>
              <button className="crumb-link" onClick={() => navigate('/')}>
                Cases
              </button>
              <Icon name="chevron" size={14} />
              <span className="crumb-current">{caseId}</span>
            </>
          ) : (
            <span className="crumb-current">{page.title}</span>
          )}
        </div>
        <h1>{page.title}</h1>
        <p>{page.sub}</p>
      </div>
    </header>
  )
}

export default function App() {
  const [path, navigate] = useHashRoute()
  const caseMatch = path.match(/^\/cases\/(.+)$/)
  const caseId = caseMatch ? decodeURIComponent(caseMatch[1]) : null

  let page
  if (caseId) {
    page = <CaseDetail caseId={caseId} />
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
        <Sidebar path={path} navigate={navigate} />
        <div className="main">
          <DemoBar />
          <PageHeader path={path} caseId={caseId} navigate={navigate} />
          <main className="content">{page}</main>
        </div>
      </div>
    </SessionProvider>
  )
}
