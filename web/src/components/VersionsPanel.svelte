<script lang="ts">
  import type { BookSession } from '../lib/book.svelte';
  import { EXPORT_LABEL, LANG_NAMES } from '../lib/store.svelte';
  import { fmtSize, fmtTime, settingsSummary } from '../lib/format';
  import type { ExportKind, VersionInfo } from '../lib/types';

  let { s }: { s: BookSession } = $props();

  const when = (t: number) => new Date(t * 1000).toLocaleString('fr', { dateStyle: 'short', timeStyle: 'short' });

  function remove(v: VersionInfo) {
    if (confirm(`Supprimer définitivement cette version (${v.voice_name ?? 'voix'}, ${when(v.created)}) ?`)) void s.deleteVersion(v.id);
  }
</script>

<!-- Chaque conversion est conservée : régénérer un livre ne remplace jamais l'audio précédent -->
{#if s.versions.length}
  <details class="kept versions">
    <summary><strong>Versions précédentes ({s.versions.length})</strong> <span class="muted small">— chaque conversion est conservée</span></summary>
    {#each s.versions as v (v.id)}
      <div class="kept-item">
        <div class="kept-meta" title={v.settings ? settingsSummary(v.settings) : ''}>
          <strong>{v.voice_name ?? 'Voix'}</strong>
          {#if v.language}· {LANG_NAMES[v.language]}{/if}
          {#if v.speed}· {v.speed.toFixed(2)}×{/if}
          {#if v.duration}· {fmtTime(v.duration)}{/if}
          {#if v.size}· {fmtSize(v.size)}{/if}
          <span class="muted">· {when(v.created)}</span>
        </div>
        <audio controls preload="none" src="/api/books/{s.id}/versions/{v.id}/audio"></audio>
        <div class="kept-links">
          <a class="btn" href="/api/books/{s.id}/versions/{v.id}/audio?download=true">⬇ MP3</a>
          {#each Object.keys(v.exports ?? {}) as kind (kind)}
            <a class="btn" href="/api/books/{s.id}/versions/{v.id}/export/{kind}">⬇ {EXPORT_LABEL[kind as ExportKind]}</a>
          {/each}
          <button class="icon-btn" title="Supprimer cette version" onclick={() => remove(v)}>✕</button>
        </div>
      </div>
    {/each}
  </details>
{/if}
