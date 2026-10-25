<script lang="ts">
  import { app } from '../lib/store.svelte';
  import type { Voice } from '../lib/types';

  let { voice, desc = '', deletable = false, compact = false }: { voice: Voice; desc?: string; deletable?: boolean; compact?: boolean } = $props();

  const liked = $derived(app.isLiked(voice.id));
  const playing = $derived(app.previewing === voice.id);

  function remove(e: MouseEvent) {
    e.stopPropagation();
    if (confirm(`Supprimer la voix « ${voice.name} » ?`)) void app.deleteVoice(voice.id);
  }
</script>

{#snippet like()}
  <button
    class="icon like"
    class:on={liked}
    title={liked ? 'Retirer des préférées' : 'Ajouter aux préférées'}
    aria-pressed={liked}
    onclick={(e) => {
      e.stopPropagation();
      app.toggleLike(voice.id);
    }}>{liked ? '♥' : '♡'}</button>
{/snippet}

{#snippet play()}
  <button
    class="icon play"
    title="Écouter un extrait"
    disabled={playing}
    onclick={(e) => {
      e.stopPropagation();
      void app.preview(voice.id);
    }}>{playing ? '…' : '▶'}</button>
{/snippet}

<div
  class="voice"
  class:compact
  class:deletable
  class:active={voice.id === app.voiceId}
  role="button"
  tabindex="0"
  onclick={() => app.selectVoice(voice.id)}
  onkeydown={(e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      app.selectVoice(voice.id);
    }
  }}
>
  {#if compact}
    <strong class="vname" title={voice.name}>{voice.name}</strong>
    {@render like()}
    {@render play()}
  {:else}
    <div class="corner">
      {@render like()}
      {#if deletable}<button class="icon" title="Supprimer cette voix" onclick={remove}>🗑</button>{/if}
    </div>
    <strong class="vname" title={voice.name}>{voice.name}</strong>
    <div class="vfoot">
      <small title={desc}>{desc}</small>
      {@render play()}
    </div>
  {/if}
</div>
