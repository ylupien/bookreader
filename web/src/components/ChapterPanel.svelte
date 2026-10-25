<script lang="ts">
  import type { BookSession } from '../lib/book.svelte';
  import { errorMessage } from '../lib/api';
  import { fmtClock } from '../lib/format';

  let { s }: { s: BookSession } = $props();

  let col = $state<HTMLElement>();

  const editing = $derived(s.editChapters !== null);
  const draft = $derived(s.book?.status === 'draft');
  const list = $derived(s.shownChapters);
  const kept = $derived(list.filter((c) => c.include).length);
  const curTitle = $derived(s.curChapter >= 0 ? s.chapters[s.curChapter]?.title : '');

  // Le chapitre en cours de lecture reste visible dans la liste
  $effect(() => {
    if (!editing && s.curChapter >= 0) col?.querySelector(`li[data-c="${s.curChapter}"]`)?.scrollIntoView({ block: 'nearest' });
  });

  async function save() {
    try {
      await s.commitEdit();
    } catch (e) {
      alert(errorMessage(e));
    }
  }
</script>

<!-- Colonne de gauche : les chapitres, à côté du texte -->
<section bind:this={col} class="chap-col">
  <div class="chap-head">
    Chapitres <span class="muted">({list.length}{kept !== list.length ? ` · ${kept} inclus` : ''})</span>
  </div>
  {#if curTitle}<div class="muted small">en cours : {curTitle}</div>{/if}
  <div class="row">
    {#if !editing}
      <button disabled={s.busy} onclick={() => s.startEdit()}>✂ Modifier le découpage</button>
    {:else if !draft}
      <button class="primary" onclick={save}>Enregistrer</button>
      <button onclick={() => s.cancelEdit()}>Annuler</button>
    {/if}
  </div>
  {#if editing}
    <p class="muted small">
      Cliquez sur un paragraphe du texte pour y faire commencer un chapitre (ou retirer ce début). Décochez les parties à ne pas inclure dans les fichiers.
    </p>
  {/if}
  <ol class="chapters">
    {#each list as c, i (c.start)}
      {#if editing}
        <li data-c={i}>
          <input type="checkbox" bind:checked={c.include} title="Inclure ce chapitre" />
          <span class="num">{i + 1}</span>
          <input type="text" bind:value={c.title} maxlength="120" />
          {#if i > 0}<button title="Fusionner avec le chapitre précédent" onclick={() => s.removeChapter(i)}>✕</button>{/if}
        </li>
      {:else}
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
        <li data-c={i} class:excluded={!c.include} class:current={i === s.curChapter} onclick={() => s.openChapter(c)}>
          <span class="num">{i + 1}</span>
          <span class="ctitle" title={c.title}>{c.title}</span>
          {#if c.time !== undefined}<span class="ctime">{fmtClock(c.time)}</span>{/if}
        </li>
      {/if}
    {/each}
  </ol>
</section>
