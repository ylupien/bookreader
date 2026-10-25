<script lang="ts">
  import type { BookSession } from '../lib/book.svelte';

  let { s }: { s: BookSession } = $props();

  let box = $state<HTMLDivElement>();

  // Pour chaque paragraphe : début de chapitre (titre) et partie exclue (chapitre décoché)
  const decor = $derived.by(() => {
    const starts = new Map(s.shownChapters.map((c, i) => [c.start, i]));
    let included = true;
    return s.paragraphs.map((_, i) => {
      const k = starts.get(i);
      if (k !== undefined) included = s.shownChapters[k].include;
      return { title: k !== undefined ? s.shownChapters[k].title : null, excluded: !included };
    });
  });
  const selected = $derived(new Set(s.sampleSel));

  function scrollToParagraph(i: number, block: 'center' | 'start') {
    const p = box?.querySelector<HTMLElement>(`p[data-i="${i}"]`);
    if (!p || !box) return;
    if (block === 'start') p.scrollIntoView({ block: 'start' });
    else box.scrollTo({ top: p.offsetTop - box.offsetTop - box.clientHeight / 3, behavior: 'smooth' });
  }

  // Suivi de la lecture : le paragraphe lu reste visible
  $effect(() => {
    if (s.follow && s.curPara >= 0) scrollToParagraph(s.curPara, 'center');
  });
  // Demande de défilement (clic sur un chapitre d'un livre pas encore converti)
  $effect(() => {
    if (s.scrollRequest) scrollToParagraph(s.scrollRequest.index, 'start');
  });

  // Un seul gestionnaire pour tous les paragraphes
  function onClick(e: MouseEvent) {
    const target = e.target as HTMLElement;
    const pick = target.closest<HTMLElement>('.pick');
    if (pick) {
      e.preventDefault(); // l'état de la case vient de la sélection, pas du clic
      return s.toggleSample(Number(pick.dataset.i), e.shiftKey);
    }
    const p = target.closest<HTMLElement>('p[data-i]');
    if (!p) return;
    const i = Number(p.dataset.i);
    if (s.editChapters) s.toggleChapterStart(i);
    else s.seekParagraph(i);
  }
</script>

<!-- Clic sur un paragraphe : début de chapitre (édition) ou lecture à cet endroit ; case à cocher : paragraphe de l'échantillon -->
<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div
  bind:this={box}
  class="text"
  class:draft={s.book?.status === 'draft'}
  class:editing={s.editChapters !== null}
  onclick={onClick}
>
  {#each s.paragraphs as para, i (i)}
    <p
      data-i={i}
      data-title={decor[i]?.title ?? undefined}
      class:chap-start={decor[i]?.title != null}
      class:excluded={decor[i]?.excluded}
      class:current={i === s.curPara}
      class:sample-pick={selected.has(i)}
    >
      <input
        type="checkbox"
        class="pick"
        data-i={i}
        checked={selected.has(i)}
        aria-label="Lire ce paragraphe dans l'échantillon"
        title="Lire ce paragraphe dans l'échantillon (Maj+clic : toute une plage)"
      />{para}
    </p>
  {/each}
</div>
