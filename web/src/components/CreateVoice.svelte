<script lang="ts">
  import { onDestroy } from 'svelte';
  import { api, errorMessage, form } from '../lib/api';
  import { app, READ_TEXT } from '../lib/store.svelte';
  import type { Voice } from '../lib/types';

  type Sample = { name: string; blob: Blob; url: string };

  let tab = $state<'clone' | 'mix'>('clone');
  let msg = $state<{ text: string; error: boolean } | null>(null);

  // --- Clonage ---
  let samples = $state.raw<Sample[]>([]);
  let cloneName = $state('');
  let consent = $state(false);
  let cloning = $state(false);
  let recording = $state(false);
  let recSeconds = $state(0);
  let recorder: MediaRecorder | null = null;
  let recTimer: number | undefined;

  function addSamples(list: Sample[]) {
    samples = [...samples, ...list];
  }

  function removeSample(i: number) {
    URL.revokeObjectURL(samples[i].url);
    samples = samples.filter((_, k) => k !== i);
  }

  function onFiles(e: Event & { currentTarget: HTMLInputElement }) {
    addSamples([...(e.currentTarget.files ?? [])].map((f) => ({ name: f.name, blob: f, url: URL.createObjectURL(f) })));
    e.currentTarget.value = '';
  }

  async function toggleRecording() {
    if (recorder) {
      recorder.stop();
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      alert('Accès au micro refusé ou indisponible.');
      return;
    }
    const chunks: Blob[] = [];
    const rec = new MediaRecorder(stream);
    recorder = rec;
    rec.ondataavailable = (ev) => chunks.push(ev.data);
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      clearInterval(recTimer);
      const blob = new Blob(chunks, { type: rec.mimeType });
      addSamples([{ name: `Enregistrement ${samples.length + 1}`, blob, url: URL.createObjectURL(blob) }]);
      recorder = null;
      recording = false;
      recSeconds = 0;
    };
    rec.start();
    recording = true;
    const t0 = Date.now();
    recTimer = window.setInterval(() => {
      recSeconds = Math.floor((Date.now() - t0) / 1000);
      if (recSeconds >= 60) rec.stop();
    }, 250);
  }

  async function clone() {
    if (!samples.length) return void (msg = { text: 'Ajoutez au moins un enregistrement.', error: true });
    if (!consent) return void (msg = { text: "Confirmez avoir l'accord de la personne enregistrée.", error: true });
    const fd = form({ name: cloneName.trim() || 'Ma voix' });
    samples.forEach((s, i) => fd.append('files', s.blob, (s.blob as File).name || `sample${i}.webm`));
    cloning = true;
    msg = { text: 'Analyse de la voix…', error: false };
    try {
      const v = await app.track({ icon: '🎙', title: cloneName.trim() || 'Ma voix', label: 'Analyse de la voix…' }, () =>
        api<Voice>('/api/voices/clone', { method: 'POST', body: fd }));
      samples.forEach((s) => URL.revokeObjectURL(s.url));
      samples = [];
      cloneName = '';
      consent = false;
      await app.voiceCreated(v);
      msg = { text: `Voix « ${v.name} » créée et sélectionnée. Écoutez-la avec ▶ dans « Mes voix ».`, error: false };
    } catch (e) {
      msg = { text: errorMessage(e), error: true };
    }
    cloning = false;
  }

  // --- Mélange ---
  let mixA = $state('');
  let mixB = $state('');
  let mixWeight = $state(50);
  let mixName = $state('');
  let mixing = $state(false);

  // Voix proposées par défaut dès que le catalogue est chargé
  $effect(() => {
    if (!mixA) mixA = app.catalog.recommended.fr?.[0]?.id ?? '';
    if (!mixB) mixB = app.catalog.recommended.en?.[2]?.id ?? '';
  });

  async function mix() {
    const a = app.voiceById(mixA), b = app.voiceById(mixB);
    const name = mixName.trim() || `${a?.name.split(' ')[0]} + ${b?.name.split(' ')[0]}`;
    mixing = true;
    try {
      const v = await app.track({ icon: '🎚', title: name, label: 'Création du mélange…' }, () =>
        api<Voice>('/api/voices/mix', {
          method: 'POST',
          body: form({ name, voice_a: mixA, voice_b: mixB, weight: mixWeight / 100 }),
        }));
      mixName = '';
      await app.voiceCreated(v);
      msg = { text: `Voix « ${v.name} » créée et sélectionnée.`, error: false };
    } catch (e) {
      msg = { text: errorMessage(e), error: true };
    }
    mixing = false;
  }

  onDestroy(() => {
    clearInterval(recTimer);
    recorder?.stop();
    samples.forEach((s) => URL.revokeObjectURL(s.url));
  });
</script>

{#snippet voiceOptions()}
  {#if app.catalog.custom.length}
    <optgroup label="Mes voix">
      {#each app.catalog.custom as v (v.id)}<option value={v.id}>{v.name}</option>{/each}
    </optgroup>
  {/if}
  <optgroup label="Voix intégrées">
    {#each app.catalog.builtin as v (v.id)}<option value={v.id}>{v.name}</option>{/each}
  </optgroup>
{/snippet}

<details id="createVoice">
  <summary>➕ Créer une voix</summary>
  <div class="seg small">
    <button class:active={tab === 'clone'} onclick={() => (tab = 'clone')}>Cloner</button>
    <button class:active={tab === 'mix'} onclick={() => (tab = 'mix')}>Mélanger</button>
  </div>

  {#if tab === 'clone'}
    <div class="panel">
      <p class="muted small">
        Fournissez 10 à 30 secondes d'une personne qui parle clairement, sans musique ni bruit de fond. Plusieurs extraits améliorent le résultat.
      </p>
      <label class="field">Nom de la voix <input type="text" bind:value={cloneName} maxlength="40" placeholder="Ex. : Ma voix" /></label>
      <div class="row">
        <button class:rec={recording} onclick={toggleRecording}>{recording ? '⏹ Arrêter' : '🎙 Enregistrer au micro'}</button>
        {#if recording}<span class="muted small">Lisez le texte ci-dessous à voix haute… {recSeconds} s</span>{/if}
      </div>
      {#if recording}<blockquote class="small">{READ_TEXT[app.lang]}</blockquote>{/if}
      <label class="field">
        Ou des fichiers audio (wav, mp3, m4a, ogg…)
        <input type="file" accept="audio/*" multiple onchange={onFiles} />
      </label>
      <ul class="samples">
        {#each samples as s, i (s.url)}
          <li>
            <span>{s.name}</span>
            <audio controls src={s.url}></audio>
            <button title="Retirer" onclick={() => removeSample(i)}>✕</button>
          </li>
        {/each}
      </ul>
      <label class="check"><input type="checkbox" bind:checked={consent} /> J'ai l'accord de la personne dont c'est la voix.</label>
      <button class="primary" disabled={cloning} onclick={clone}>Créer la voix</button>
    </div>
  {:else}
    <div class="panel">
      <label class="field">Voix A <select bind:value={mixA}>{@render voiceOptions()}</select></label>
      <label class="field">Voix B <select bind:value={mixB}>{@render voiceOptions()}</select></label>
      <label class="field">
        Proportion : <span>{mixWeight} % A · {100 - mixWeight} % B</span>
        <input type="range" min="0" max="100" step="5" bind:value={mixWeight} />
      </label>
      <label class="field">Nom de la voix <input type="text" bind:value={mixName} maxlength="40" placeholder="Ex. : Mélange doux" /></label>
      <button class="primary" disabled={mixing || !mixA || !mixB} onclick={mix}>Créer le mélange</button>
    </div>
  {/if}
  {#if msg}<div class="msg" class:error={msg.error}>{msg.text}</div>{/if}
</details>
