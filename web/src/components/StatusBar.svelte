<script lang="ts">
  import { app, EXPORT_LABEL } from '../lib/store.svelte';
  import { fmtDur, fmtTime, pct, timerText } from '../lib/format';

  const RECENT_DONE_SEC = 15 * 60;

  type Task = { key: string; icon: string; title: string; label: string; bookId?: string; percent?: number; error?: boolean; cancel?: () => void };

  // Tout le travail en cours : extractions, conversions, exports, erreurs, livres terminés récemment
  const tasks = $derived.by(() => {
    const rows: Task[] = [];
    for (const t of app.localTasks) {
      const pc = t.percent !== undefined ? ` ${t.percent} %` : '';
      rows.push({
        key: `local:${t.id}`, icon: t.icon, title: t.title, bookId: t.bookId, percent: t.percent, cancel: t.cancel,
        label: `${t.label}${pc} · ${fmtDur((app.now - t.since) / 1000)}`,
      });
    }
    for (const b of app.books) {
      if (b.status === 'processing' || b.status === 'queued') {
        const timer = timerText(b, app.now);
        rows.push({
          key: b.id, icon: b.status === 'queued' ? '🕓' : '🔊', title: b.title, bookId: b.id, percent: pct(b.progress),
          label: b.status === 'queued' ? 'En attente' : `Conversion ${pct(b.progress)} %${timer ? ` · ${timer}` : ''}`,
          cancel: () => void app.cancelConversion(b),
        });
      } else if (b.status === 'error') {
        rows.push({ key: b.id, icon: '⚠', title: b.title, bookId: b.id, label: b.error || 'Erreur', error: true });
      } else if (b.status === 'done' && b.finished_at && app.now / 1000 - b.finished_at < RECENT_DONE_SEC) {
        rows.push({ key: b.id, icon: '✔', title: b.title, bookId: b.id, label: `Terminé · ${fmtTime(b.duration)}` });
      }
      for (const [kind, ex] of Object.entries(b.exports ?? {})) {
        const name = EXPORT_LABEL[kind as keyof typeof EXPORT_LABEL] ?? kind;
        if (ex?.status === 'pending' || ex?.status === 'working') {
          const p = Math.round((ex.progress ?? 0) * 100);
          rows.push({ key: `${b.id}:${kind}`, icon: '📦', title: b.title, bookId: b.id, percent: p, label: `Export ${name} · ${p} %` });
        } else if (ex?.status === 'error') {
          rows.push({ key: `${b.id}:${kind}`, icon: '⚠', title: b.title, bookId: b.id, label: `Export ${name} : ${ex.error || 'erreur'}`, error: true });
        }
      }
    }
    return rows;
  });
</script>

{#snippet body(t: Task)}
  <span class="ico">{t.icon}</span>
  <div class="tinfo">
    <div class="tline"><span class="ttitle">{t.title}</span><small>{t.label}</small></div>
    {#if t.percent !== undefined}<div class="bar"><div style="width:{t.percent}%"></div></div>{/if}
  </div>
  {#if t.cancel}
    <button
      class="mini"
      title="Annuler"
      onclick={(e) => {
        e.stopPropagation();
        t.cancel?.();
      }}>⏹ Annuler</button>
  {/if}
{/snippet}

<!-- Toujours visible, quelle que soit la vue -->
<footer id="statusbar">
  <div class="sb-title">État du travail</div>
  <div id="tasks">
    {#each tasks as t (t.key)}
      {#if t.bookId}
        {@const bookId = t.bookId}
        <div
          class="task"
          class:err={t.error}
          data-open={bookId}
          role="button"
          tabindex="0"
          title="Ouvrir ce livre"
          onclick={() => (app.openId = bookId)}
          onkeydown={(e) => e.key === 'Enter' && (app.openId = bookId)}
        >{@render body(t)}</div>
      {:else}
        <div class="task" class:err={t.error}>{@render body(t)}</div>
      {/if}
    {:else}
      <span class="muted">Aucune tâche en cours.</span>
    {/each}
  </div>
</footer>
