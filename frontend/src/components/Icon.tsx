import type { ReactNode } from 'react'

// Line icons drawn inline (no icon library). 24px grid, stroke follows currentColor.
const PATHS = {
  cases: (
    <>
      <rect x="3.5" y="6.5" width="17" height="13" rx="2.2" />
      <path d="M9 6.5V5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5v1.5M3.5 12h17" />
    </>
  ),
  review: (
    <>
      <path d="M4 13.5 6.4 6a2 2 0 0 1 1.9-1.4h7.4A2 2 0 0 1 17.6 6l2.4 7.5" />
      <path d="M4 13.5h4.5l1.5 2.5h4l1.5-2.5H20v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" />
    </>
  ),
  audit: (
    <>
      <path d="M12 3 4.5 6v6c0 4.6 3.2 7.8 7.5 9 4.3-1.2 7.5-4.4 7.5-9V6z" />
      <path d="m8.8 12.2 2.2 2.2 4.4-4.6" />
    </>
  ),
  chevron: <path d="m9 6 6 6-6 6" />,
  play: <path d="M7 5.5v13l11-6.5z" />,
  reset: (
    <>
      <path d="M4 12a8 8 0 1 0 2.4-5.7" />
      <path d="M4 4.5v4h4" />
    </>
  ),
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  alert: (
    <>
      <path d="M12 3.5 2.8 19.5h18.4z" />
      <path d="M12 10v4.2M12 17v.1" />
    </>
  ),
  close: <path d="M6 6l12 12M18 6 6 18" />,
  mail: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2.5" />
      <path d="m3.5 6.5 8.5 6.5 8.5-6.5" />
    </>
  ),
  database: (
    <>
      <ellipse cx="12" cy="6" rx="7.5" ry="3" />
      <path d="M4.5 6v12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6M4.5 12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3" />
    </>
  ),
  download: <path d="M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M5 19.5h14" />,
  link: (
    <>
      <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" />
      <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />
    </>
  ),
  spark: <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18" />,
  user: (
    <>
      <circle cx="12" cy="8.5" r="3.5" />
      <path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5" />
    </>
  ),
  archive: (
    <>
      <rect x="3.5" y="4" width="17" height="4.5" rx="1.2" />
      <path d="M5 8.5V18a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5M10 12.5h4" />
    </>
  ),
  doc: (
    <>
      <path d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10A1.5 1.5 0 0 1 6 19V5a1.5 1.5 0 0 1 1-1.5z" />
      <path d="M14 3.5V8h4M9 12.5h6M9 16h6" />
    </>
  ),
} satisfies Record<string, ReactNode>

export type IconName = keyof typeof PATHS

export function Icon({ name, size = 18, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      className={`icon ${className ?? ''}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name]}
    </svg>
  )
}

// The capsule mark from the pitch deck: one solid half, one glass half.
export function LogoMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none" aria-hidden="true" className="logo-mark">
      <defs>
        <linearGradient id="tp-cap-a" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#b6d6ff" />
          <stop offset=".45" stopColor="#3d7dff" />
          <stop offset="1" stopColor="#1636a8" />
        </linearGradient>
        <linearGradient id="tp-cap-b" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" stopOpacity=".6" />
          <stop offset="1" stopColor="#8fe9ff" stopOpacity=".18" />
        </linearGradient>
      </defs>
      <g transform="rotate(-35 20 20)">
        <path d="M20 12h-8a8 8 0 0 0 0 16h8z" fill="url(#tp-cap-a)" />
        <path d="M20 12h8a8 8 0 0 1 0 16h-8z" fill="url(#tp-cap-b)" stroke="#bfeaff" strokeOpacity=".75" />
        <circle cx="24.5" cy="18" r="1.4" fill="#e6fbff" />
        <circle cx="27.2" cy="22" r="1.1" fill="#bdf3ff" />
        <path d="M8.5 15.2h9" stroke="#fff" strokeOpacity=".5" strokeWidth="1.4" strokeLinecap="round" />
      </g>
    </svg>
  )
}
