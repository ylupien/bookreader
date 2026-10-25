<script lang="ts">
  import { app } from '../lib/store.svelte';
  import type { Settings } from '../lib/types';

  const FIELDS: { key: keyof Settings; label: string; step: number; unit?: string; help: string }[] = [
    { key: 'temperature', label: 'Expressivité', step: 0.05, help: 'Bas : stable mais monotone. Haut : plus vivant, risque de bizarreries.' },
    { key: 'top_p', label: "Variété de l'intonation", step: 0.05, help: "Bas : intonation prévisible. Haut : plus de variations." },
    { key: 'repetition_penalty', label: 'Anti-répétition', step: 0.5, help: 'À augmenter si la voix bégaie ou répète des sons.' },
    { key: 'sentence_pause', label: 'Pause entre phrases', step: 0.05, unit: ' s', help: 'Silence ajouté après chaque phrase.' },
    { key: 'paragraph_pause', label: 'Pause entre paragraphes', step: 0.1, unit: ' s', help: 'Silence ajouté après chaque paragraphe.' },
  ];

  let tryText = $state('');
</script>

<details id="advanced">
  <summary>⚙ Réglages avancés</summary>
  <div class="settings">
    {#if app.config}
      {#each FIELDS as f (f.key)}
        <label>
          {f.label} : <span class="val">{app.settings[f.key]}{f.unit ?? ''}</span>
          <input
            type="range"
            min={app.config.limits[f.key][0]}
            max={app.config.limits[f.key][1]}
            step={f.step}
            value={app.settings[f.key]}
            oninput={(e) => app.setSetting(f.key, Number(e.currentTarget.value))}
          />
          <small>{f.help}</small>
        </label>
      {/each}
    {/if}
  </div>
  <label class="field">
    Texte d'essai
    <input type="text" bind:value={tryText} maxlength="300" placeholder="Laissez vide pour la phrase par défaut" />
  </label>
  <div class="row">
    <button class="primary" disabled={!app.voiceId} onclick={() => app.voiceId && app.preview(app.voiceId, tryText.trim())}>
      ▶ Essayer ces réglages
    </button>
    <button onclick={() => app.resetSettings()}>Réinitialiser</button>
  </div>
</details>
