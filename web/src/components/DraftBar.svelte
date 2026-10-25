<script lang="ts">
  import type { BookSession } from '../lib/book.svelte';
  import { errorMessage } from '../lib/api';
  import { app, LANG_NAMES } from '../lib/store.svelte';
  import SamplesList from './SamplesList.svelte';

  let { s }: { s: BookSession } = $props();

  let generating = $state(false);
  let starting = $state(false);

  const count = $derived(s.sampleSel.length);
  const plural = (n: number) => (n > 1 ? 's' : '');
  const sampleLabel = $derived(count ? `${count} paragraphe${plural(count)} coché${plural(count)}` : 'les 2 premiers paragraphes');
  const numbers = $derived(s.sampleSel.map((i) => i + 1).join(', '));

  async function sample() {
    if (!app.voiceId) return void alert("Choisissez d'abord une voix.");
    generating = true;
    try {
      await s.makeSample();   // l'échantillon est conservé et se lance tout seul dans la liste (null : annulé)
    } catch (e) {
      alert(errorMessage(e));
    }
    generating = false;
  }

  async function start() {
    if (!app.voiceId) return void alert("Choisissez d'abord une voix.");
    starting = true;
    try {
      await s.startConversion();
    } catch (e) {
      alert(errorMessage(e));
    }
    starting = false;
  }
</script>

<div class="msg">
  <p>
    {#if s.book?.mode === 'chapters'}Vérifiez le découpage en chapitres (titres, parties à ignorer). {/if}Réglez la voix, la langue, la vitesse et les
    réglages avancés dans la barre de gauche, écoutez un échantillon, puis convertissez tout le livre.
  </p>
  <p>
    <strong>Échantillon :</strong> cochez dans le texte les paragraphes à écouter (Maj+clic pour une plage). Sans case cochée, ce sont les deux
    premiers paragraphes.
  </p>
  <p class="muted">
    Sera utilisé : {app.voice?.name ?? 'aucune voix choisie'} · {LANG_NAMES[app.lang]} · vitesse {app.speed.toFixed(2)}× · échantillon : {sampleLabel}{count ? ` (n° ${numbers})` : ''}
    {#if count}<button class="linkish" onclick={() => s.clearSample()}>Tout décocher</button>{/if}
  </p>
  <div class="row">
    <button disabled={generating || starting} title="Lit les paragraphes cochés (ou les deux premiers) avec la voix et les réglages actuels" onclick={sample}>
      {generating ? `Génération de l'échantillon… ${s.sampleProgress ?? 0} %` : `🎧 Échantillon (${count || 2} paragraphe${plural(count || 2)})`}
    </button>
    {#if generating}<button onclick={() => s.cancelSample()}>⏹ Annuler</button>{/if}
    <button class="primary" disabled={generating || starting} onclick={start}>▶ Convertir tout le livre</button>
  </div>
  <SamplesList {s} />
</div>
