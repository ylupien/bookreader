<script lang="ts">
  import type { BookSession } from '../lib/book.svelte';
  import { LANG_NAMES } from '../lib/store.svelte';
  import { settingsSummary } from '../lib/format';

  let { s }: { s: BookSession } = $props();

  const when = (t: number) => new Date(t * 1000).toLocaleString('fr', { dateStyle: 'short', timeStyle: 'short' });
</script>

<!-- Échantillons conservés : ils restent quand on quitte le livre, jusqu'à ce qu'on les supprime -->
{#if s.samples.length}
  <div class="kept">
    <div class="kept-head">
      <strong>Échantillons conservés ({s.samples.length})</strong>
      {#if s.samples.length > 1}
        <button class="linkish" onclick={() => confirm('Supprimer tous les échantillons de ce livre ?') && Promise.all(s.samples.map((x) => s.deleteSample(x.id)))}>Tout supprimer</button>
      {/if}
    </div>
    {#each s.samples as x (x.id)}
      <div class="kept-item">
        <div class="kept-meta" title={x.settings ? settingsSummary(x.settings) : ''}>
          <strong>{x.voice_name ?? 'Voix'}</strong>
          {#if x.language}· {LANG_NAMES[x.language]}{/if}
          {#if x.speed}· {x.speed.toFixed(2)}×{/if}
          {#if x.paragraphs?.length}· ¶ {x.paragraphs.map((i) => i + 1).join(', ')}{/if}
          {#if x.duration}· {Math.round(x.duration)} s{/if}
          <span class="muted">· {when(x.created)}</span>
        </div>
        <audio controls preload="none" src="/api/books/{s.id}/samples/{x.id}/audio" autoplay={x.id === s.lastSampleId}></audio>
        <button class="icon-btn" title="Supprimer cet échantillon" onclick={() => s.deleteSample(x.id)}>✕</button>
      </div>
    {/each}
  </div>
{/if}
