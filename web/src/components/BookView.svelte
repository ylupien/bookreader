<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import { BookSession } from '../lib/book.svelte';
  import { errorMessage } from '../lib/api';
  import { app, LANG_NAMES, STATUS } from '../lib/store.svelte';
  import { fmtTime, pct, timerText } from '../lib/format';
  import type { Lang } from '../lib/types';
  import DraftBar from './DraftBar.svelte';
  import Downloads from './Downloads.svelte';
  import VersionsPanel from './VersionsPanel.svelte';
  import ChapterPanel from './ChapterPanel.svelte';
  import BookText from './BookText.svelte';

  let { id }: { id: string } = $props();

  const s = new BookSession(untrack(() => id));
  let audioEl = $state<HTMLAudioElement>();
  let rate = $state(1);
  let regenVoice = $state('');
  let regenLang = $state<Lang>('fr');
  let restored = false;

  const book = $derived(s.book);
  const done = $derived(book?.status === 'done');
  const draft = $derived(book?.status === 'draft');
  const audioSrc = $derived(book && done ? `/api/books/${id}/audio?v=${book.created}-${book.duration}` : undefined);

  const info = $derived.by(() => {
    const b = book;
    if (!b) return '';
    if (b.status === 'done') return `${b.voice_name} · ${LANG_NAMES[b.language]} · ${fmtTime(b.duration)}`;
    if (b.status === 'draft') return `${b.chars.toLocaleString('fr')} caractères · ${b.chapter_count} chapitres`;
    const progress = b.status === 'processing' ? ` ${pct(b.progress)} %` : '';
    return `${STATUS[b.status]}${progress}${b.error ? ' : ' + b.error : ''} — l'audio sera disponible à la fin de la conversion.`;
  });

  onMount(() => {
    document.getElementById('content')?.scrollTo(0, 0);
    s.load().then(() => {
      regenVoice = s.book?.voice ?? '';
      regenLang = s.book?.language ?? 'fr';
    }).catch((e) => {
      alert(errorMessage(e));
      app.openId = null;
    });
  });

  // Le sondage de la bibliothèque met à jour ce livre (progression, fin de conversion, exports)
  $effect(() => {
    const b = app.openBook;
    if (b) untrack(() => void s.sync(b));
  });
  $effect(() => {
    s.audio = audioEl ?? null;
  });
  $effect(() => {
    if (audioEl) {
      audioEl.defaultPlaybackRate = rate;
      audioEl.playbackRate = rate;
    }
  });
  onDestroy(() => {
    s.savePosition();
    s.audio?.pause();
  });

  function back() {
    app.openId = null;
  }

  async function regenerate() {
    try {
      await s.regenerate(regenVoice, regenLang);
    } catch (e) {
      alert(errorMessage(e));
    }
  }

  function onLoadedMetadata() {
    if (restored) return;
    restored = true;
    s.restorePosition();
  }
</script>

<svelte:window onbeforeunload={() => s.savePosition()} />

<section class="card" id="player">
  {#if book}
    <div class="player-head">
      <div>
        <button class="back-lib" title="Retour à la bibliothèque" onclick={back}>← Bibliothèque</button>
        <h2>{book.title}</h2>
        <small class="muted">{info}</small>
        <small class="muted timer">{timerText(book, app.now)}</small>
        {#if s.busy}
          <button class="cancel-conv" onclick={() => app.cancelConversion(book)}>⏹ Annuler la conversion</button>
        {/if}
      </div>
    </div>

    {#if done}
      <audio
        bind:this={audioEl}
        controls
        preload="metadata"
        src={audioSrc}
        onloadedmetadata={onLoadedMetadata}
        ontimeupdate={() => s.onTimeUpdate()}
        onpause={() => s.savePosition()}
      ></audio>
      <div class="controls">
        <button onclick={() => audioEl && (audioEl.currentTime = Math.max(0, audioEl.currentTime - 15))}>⏪ 15 s</button>
        <button onclick={() => audioEl && (audioEl.currentTime += 15)}>15 s ⏩</button>
        <label>
          Vitesse
          <select bind:value={rate}>
            {#each [0.75, 1, 1.25, 1.5, 2] as r (r)}<option value={r}>{r}</option>{/each}
          </select>
        </label>
        <label><input type="checkbox" bind:checked={s.follow} /> Suivre le texte</label>
      </div>
      <Downloads {s} />
    {/if}

    {#if s.ready}<VersionsPanel {s} />{/if}

    {#if !draft}
      <div class="regen">
        Régénérer avec
        <select bind:value={regenVoice}>
          {#if app.catalog.custom.length}
            <optgroup label="Mes voix">
              {#each app.catalog.custom as v (v.id)}<option value={v.id}>{v.name}</option>{/each}
            </optgroup>
          {/if}
          <optgroup label="Voix intégrées">
            {#each app.catalog.builtin as v (v.id)}<option value={v.id}>{v.name}</option>{/each}
          </optgroup>
        </select>
        <select bind:value={regenLang}>
          <option value="fr">Français</option>
          <option value="en">English</option>
        </select>
        <button disabled={s.busy} title="Utilise la vitesse et les réglages avancés de la barre de gauche" onclick={regenerate}>
          Régénérer
        </button>
      </div>
    {:else}
      <DraftBar {s} />
    {/if}

    {#if s.ready}
      <div class="book-body">
        <ChapterPanel {s} />
        <BookText {s} />
      </div>
    {:else}
      <p class="muted">Chargement du texte…</p>
    {/if}
  {:else}
    <p class="muted">Chargement…</p>
  {/if}
</section>
