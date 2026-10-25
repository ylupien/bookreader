import type { Book, Settings } from './types';

export function fmtTime(sec: number | undefined): string {
  const s0 = Math.round(sec || 0);
  const h = Math.floor(s0 / 3600), m = Math.floor((s0 % 3600) / 60), s = s0 % 60;
  return h ? `${h} h ${String(m).padStart(2, '0')} min` : `${m} min ${String(s).padStart(2, '0')} s`;
}

export function fmtDur(sec: number): string {
  const s0 = Math.max(0, Math.round(sec));
  const h = Math.floor(s0 / 3600), m = Math.floor((s0 % 3600) / 60), s = s0 % 60;
  if (h) return `${h} h ${String(m).padStart(2, '0')} min`;
  if (m) return `${m} min ${String(s).padStart(2, '0')} s`;
  return `${s} s`;
}

export function fmtClock(sec: number): string {
  const s0 = Math.round(sec);
  const h = Math.floor(s0 / 3600), m = Math.floor((s0 % 3600) / 60), s = s0 % 60;
  return (h ? `${h}:${String(m).padStart(2, '0')}` : `${m}`) + `:${String(s).padStart(2, '0')}`;
}

export function fmtSize(bytes: number): string {
  if (bytes > 1e9) return `${(bytes / 1e9).toFixed(1)} Go`;
  return bytes > 1e6 ? `${Math.round(bytes / 1e6)} Mo` : `${Math.max(1, Math.round(bytes / 1e3))} Ko`;
}

export const pct = (p: number | undefined): number => Math.round((p || 0) * 1000) / 10;

/** Minuterie d'un livre : temps écoulé et reste estimé (conversion), durée totale (terminé). */
export function timerText(b: Book, nowMs: number): string {
  if (b.status === 'processing') {
    const elapsed = nowMs / 1000 - (b.started_at || b.created);
    const p = b.progress || 0;
    const eta = p > 0.002 ? ` · reste ≈ ${fmtDur((elapsed * (1 - p)) / p)}` : ' · estimation en cours…';
    return `⏱ ${fmtDur(elapsed)}${eta}`;
  }
  if (b.status === 'done' && b.started_at && b.finished_at) return `converti en ${fmtDur(b.finished_at - b.started_at)}`;
  return '';
}

/** Réglages de voix en une ligne (infobulle des échantillons et des versions conservés). */
export function settingsSummary(s: Settings): string {
  return `Expressivité ${s.temperature} · Variété ${s.top_p} · Anti-répétition ${s.repetition_penalty} · Pause phrases ${s.sentence_pause} s · Pause paragraphes ${s.paragraph_pause} s`;
}
