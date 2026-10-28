// FIXTURES ONLY: sample data for offline UI work, generated from data/seed by
// scripts/make_fixtures.py (runs the K3 API demo stub). Not real case data.
import type { AuditEvent, Case, Email } from '../types/contracts'
import type { ApiDraft, Directory } from '../api'
import auditJson from './audit.json'
import casesJson from './cases.json'
import directoryJson from './directory.json'
import draftsJson from './drafts.json'
import emailsJson from './emails.json'

export const fixtureCases = casesJson as unknown as Case[]
export const fixtureDrafts = draftsJson as unknown as ApiDraft[]
export const fixtureAudit = auditJson as unknown as AuditEvent[]
export const fixtureEmails = emailsJson as unknown as Email[]
export const fixtureDirectory = directoryJson as unknown as Directory
