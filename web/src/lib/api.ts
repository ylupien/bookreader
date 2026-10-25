// Appel de l'API : lève une Error avec le message du serveur (champ « detail ») en cas d'échec
async function fail(r: Response): Promise<never> {
  let detail: unknown = r.statusText;
  try {
    detail = (await r.json()).detail || detail;
  } catch {
    /* corps non JSON */
  }
  throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
}

export async function api<T>(url: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(url, opts);
  if (!r.ok) await fail(r);
  return r.json() as Promise<T>;
}

export async function apiText(url: string): Promise<string> {
  const r = await fetch(url);
  if (!r.ok) await fail(r);
  return r.text();
}

export async function apiBlob(url: string): Promise<Blob> {
  const r = await fetch(url);
  if (!r.ok) await fail(r);
  return r.blob();
}

export function form(fields: Record<string, string | number | boolean>): FormData {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.append(k, String(v));
  return fd;
}

export const errorMessage = (e: unknown): string => (e instanceof Error ? e.message : String(e));
