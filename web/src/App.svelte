<script lang="ts">
  import { onMount } from 'svelte';
  import { app } from './lib/store.svelte';
  import Sidebar from './components/Sidebar.svelte';
  import Library from './components/Library.svelte';
  import BookView from './components/BookView.svelte';
  import StatusBar from './components/StatusBar.svelte';

  onMount(() => {
    void app.init();
  });

  // Le livre ouvert est dans l'adresse (#livre=<id>) : un rechargement de la page le garde ouvert
  $effect(() => {
    history.replaceState(null, '', app.openId ? `#livre=${app.openId}` : location.pathname + location.search);
  });
</script>

<!-- Un fichier lâché à côté de la zone de dépôt ne doit pas faire quitter la page -->
<svelte:window ondragover={(e) => e.preventDefault()} ondrop={(e) => e.preventDefault()} />

<div id="app">
  <Sidebar />
  <main id="content">
    {#if app.openId}
      {#key app.openId}
        <BookView id={app.openId} />
      {/key}
    {:else}
      <Library />
    {/if}
  </main>
  <StatusBar />
</div>
