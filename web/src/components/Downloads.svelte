<script lang="ts">
  import type { BookSession } from '../lib/book.svelte';
  import { errorMessage } from '../lib/api';
  import { EXPORT_LABEL } from '../lib/store.svelte';
  import { fmtSize } from '../lib/format';
  import type { ExportKind } from '../lib/types';

  let { s }: { s: BookSession } = $props();

  const KINDS: ExportKind[] = ['zip', 'm4b'];

  async function request(kind: ExportKind) {
    try {
      await s.requestExport(kind);
    } catch (e) {
      alert(errorMessage(e));
    }
  }
</script>

{#if s.book?.status === 'done'}
  {@const b = s.book}
  <div class="row downloads">
    <span class="muted">Télécharger :</span>
    <a class="btn" href="/api/books/{b.id}/audio?download=true">⬇ MP3 complet</a>
    {#each KINDS as kind (kind)}
      {@const ex = b.exports?.[kind]}
      {@const label = EXPORT_LABEL[kind]}
      {#if ex?.status === 'ready'}
        <a class="btn" href="/api/books/{b.id}/export/{kind}?r={b.export_rev || 0}">⬇ {label}{ex.size ? ` · ${fmtSize(ex.size)}` : ''}</a>
      {:else if ex?.status === 'pending' || ex?.status === 'working'}
        <span class="muted">⏳ {label} : préparation… {Math.round((ex.progress || 0) * 100)} %</span>
      {:else if ex?.status === 'error'}
        <button title={ex.error ?? ''} onclick={() => request(kind)}>⚠ {label} : réessayer</button>
      {:else}
        <button onclick={() => request(kind)}>Préparer : {label}</button>
      {/if}
    {/each}
  </div>
{/if}
