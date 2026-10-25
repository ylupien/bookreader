<script lang="ts">
  import { app, LANG_NAMES, STATUS } from '../lib/store.svelte';
  import { fmtTime, pct, timerText } from '../lib/format';
  import type { Book } from '../lib/types';

  let over = $state(false);

  function detail(b: Book): string {
    let d = `${b.voice_name} · ${LANG_NAMES[b.language]}`;
    if (b.mode === 'chapters') d += ` · ${b.chapter_count} chapitres`;
    if (b.status === 'done') d += ` · ${fmtTime(b.duration)}`;
    else if (b.status === 'processing') d += ` · ${pct(b.progress)} %`;
    else if (b.status === 'error') d += ` · ${b.error ?? ''}`;
    return d;
  }

  const actionLabel = (b: Book) => (b.status === 'done' ? '▶ Écouter' : b.status === 'draft' ? '✎ Préparer' : 'Ouvrir');

  function onPick(e: Event & { currentTarget: HTMLInputElement }) {
    const files = [...(e.currentTarget.files ?? [])];
    e.currentTarget.value = '';
    void app.uploadFiles(files);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    over = false;
    void app.uploadFiles([...(e.dataTransfer?.files ?? [])]);
  }
</script>

<section id="library">
  <div class="lib-head">
    <h2>Bibliothèque</h2>
    {#if app.books.length}<small class="muted">{app.books.length} livre{app.books.length > 1 ? 's' : ''}</small>{/if}
  </div>

  <div class="shelf">
    {#each app.books as b (b.id)}
      <div class="book" role="button" tabindex="0" onclick={() => (app.openId = b.id)}
        onkeydown={(e) => e.key === 'Enter' && (app.openId = b.id)}>
        <div class="info">
          <span class="badge {b.status}">{STATUS[b.status]}</span>
          <div class="title" title={b.title}>{b.title}</div>
          <small>{detail(b)}</small>
          {#if timerText(b, app.now)}<small class="timer">{timerText(b, app.now)}</small>{/if}
          {#if b.status === 'processing' || b.status === 'queued'}
            <div class="bar"><div style="width:{pct(b.progress)}%"></div></div>
          {/if}
        </div>
        <div class="actions">
          <button onclick={(e) => { e.stopPropagation(); app.openId = b.id; }}>{actionLabel(b)}</button>
          <button title="Supprimer" onclick={(e) => { e.stopPropagation(); void app.deleteBook(b); }}>🗑</button>
        </div>
      </div>
    {:else}
      <p class="muted">Aucun livre pour l'instant. Déposez un fichier ci-dessous pour commencer.</p>
    {/each}
  </div>

  <div class="drop-wrap">
    <label
      class="drop"
      class:over
      ondragenter={(e) => { e.preventDefault(); over = true; }}
      ondragover={(e) => { e.preventDefault(); over = true; }}
      ondragleave={() => (over = false)}
      ondrop={onDrop}
    >
      <input type="file" hidden multiple accept={app.config?.formats.join(',')} onchange={onPick} />
      <div><strong>Déposez un ou plusieurs fichiers ici</strong> ou cliquez pour choisir</div>
      {#if app.config}<small>Formats : {app.config.formats.join(', ')}</small>{/if}
    </label>
    {#if app.uploadMsg}<div class="msg" class:error={app.uploadMsg.error}>{app.uploadMsg.text}</div>{/if}
  </div>
</section>
