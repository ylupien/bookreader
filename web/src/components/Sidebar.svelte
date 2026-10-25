<script lang="ts">
  import { app, LANG_NAMES, MODE_HELP } from '../lib/store.svelte';
  import type { Lang, Mode } from '../lib/types';
  import VoiceCard from './VoiceCard.svelte';
  import CreateVoice from './CreateVoice.svelte';
  import AdvancedSettings from './AdvancedSettings.svelte';

  let query = $state('');
  const builtin = $derived.by(() => {
    const q = query.trim().toLowerCase();
    return app.catalog.builtin.filter((v) => !q || v.name.toLowerCase().includes(q));
  });
  const LANGS: Lang[] = ['fr', 'en'];
  const MODES: { id: Mode; label: string }[] = [
    { id: 'single', label: 'Fichier unique' },
    { id: 'chapters', label: 'Par chapitre' },
  ];
</script>

<!-- Voix et réglages utilisés pour les prochains échantillons et conversions -->
<aside id="sidebar">
  <div class="brand">
    <h1>📖 BookReader</h1>
    <p>Transformez vos documents en livres audio</p>
  </div>

  <section class="side">
    <h2>Langue du livre</h2>
    <div class="seg">
      {#each LANGS as l (l)}
        <button class:active={app.lang === l} onclick={() => app.setLang(l)}>{LANG_NAMES[l]}</button>
      {/each}
    </div>
  </section>

  <section class="side">
    <h2>Voix {#if app.voice}<span class="muted small">— {app.voice.name}</span>{/if}</h2>
    {#if !app.catalogReady}<div class="muted">Chargement du modèle de voix…</div>{/if}
    <h3>Préférées</h3>
    <div class="voices">
      {#each app.likedVoices as v (v.id)}
        <VoiceCard voice={v} desc={app.descOf(v.id)} />
      {:else}
        {#if app.catalogReady}<p class="muted small">Aucune voix préférée : cliquez sur ♡ sur une voix pour l'ajouter ici.</p>{/if}
      {/each}
    </div>

    {#if app.catalog.custom.length}
      <h3>Mes voix</h3>
      <div class="voices">
        {#each app.catalog.custom as v (v.id)}
          <VoiceCard voice={v} desc={v.info} deletable />
        {/each}
      </div>
    {/if}

    <details>
      <summary>Toutes les voix intégrées <span class="muted">({app.catalog.builtin.length})</span></summary>
      <input type="search" bind:value={query} placeholder="Rechercher une voix…" />
      <div class="voices compact">
        {#each builtin as v (v.id)}
          <VoiceCard voice={v} compact />
        {:else}
          <p class="muted small">Aucune voix trouvée.</p>
        {/each}
      </div>
    </details>

    <CreateVoice />
  </section>

  <section class="side">
    <h2>Vitesse <span id="speedVal">{app.speed.toFixed(2)}×</span></h2>
    <input type="range" min="0.7" max="1.3" step="0.05" bind:value={app.speed} />
  </section>

  <section class="side">
    <AdvancedSettings />
  </section>

  <section class="side">
    <h2>Format des prochains imports</h2>
    <div class="seg">
      {#each MODES as m (m.id)}
        <button class:active={app.mode === m.id} onclick={() => app.setMode(m.id)}>{m.label}</button>
      {/each}
    </div>
    <p class="muted small">{MODE_HELP[app.mode]}</p>
  </section>
</aside>
