import { api, errorMessage, form } from './api';
import { store } from './storage';
import type { Book, Catalog, Config, Lang, Mode, Settings, Status, Voice } from './types';

export const LANG_NAMES: Record<Lang, string> = { fr: 'Français', en: 'English' };
export const STATUS: Record<Status, string> = {
  draft: 'À préparer', queued: 'En attente', processing: 'Conversion', done: 'Prêt', error: 'Erreur',
};
export const EXPORT_LABEL = { zip: 'Chapitres (ZIP de MP3)', m4b: 'M4B avec chapitres' } as const;
export const MODE_HELP: Record<Mode, string> = {
  single: "Un seul MP3 pour tout le livre. Les chapitres restent accessibles dans le lecteur, et vous pourrez quand même exporter par chapitre.",
  chapters: "Les chapitres sont détectés automatiquement ; vous pourrez les vérifier avant la conversion. À la fin : un MP3 par chapitre (ZIP) et un livre audio M4B avec chapitres.",
};
export const READ_TEXT: Record<Lang, string> = {
  fr: "Le soleil se levait doucement sur la ville encore endormie. Dans la petite boulangerie du coin, on préparait déjà le pain chaud et les croissants. Les premiers passants pressaient le pas, emmitouflés dans leurs manteaux, tandis qu'au loin une cloche sonnait sept heures. Quelle belle journée s'annonçait !",
  en: "The sun was rising slowly over the sleeping city. In the little bakery on the corner, fresh bread and pastries were already coming out of the oven. The first passers-by hurried along, wrapped in their coats, while in the distance a bell rang seven o'clock. What a beautiful day it was going to be!",
};

/** Travail sans pourcentage (échantillon, extrait de voix, extraction…) : la barre d'état affiche un chronomètre. */
export interface LocalTask {
  id: number;
  icon: string;
  title: string;
  label: string;
  bookId?: string;
  since: number;
  percent?: number;        // avancement 0-100 quand il est connu
  cancel?: () => void;     // affiche un bouton « Annuler »
}

const DEFAULT_SPEED = 1;   // vitesse de lecture par défaut : 1× (réglable de 0,7× à 1,3×)
const initialHash = location.hash;   // lu avant que l'interface ne réécrive l'adresse
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** État partagé de toute l'interface (Svelte 5 : les champs $state rendent l'affichage réactif). */
class App {
  config = $state<Config | null>(null);
  catalog = $state<Catalog>({ recommended: { fr: [], en: [] }, builtin: [], custom: [] });
  catalogReady = $state(false);
  lang = $state<Lang>('fr');
  selectedVoice = $state<Partial<Record<Lang, string>>>({});
  settings = $state<Settings>({ temperature: 0.75, top_p: 0.85, repetition_penalty: 5, sentence_pause: 0.25, paragraph_pause: 0.8 });
  speed = $state(DEFAULT_SPEED);
  mode = $state<Mode>('single');
  books = $state<Book[]>([]);
  openId = $state<string | null>(null);
  localTasks = $state<LocalTask[]>([]);         // travail lancé depuis cette page (barre d'état)
  uploadMsg = $state<{ text: string; error: boolean } | null>(null);
  now = $state(Date.now());                     // tic d'une seconde pour les minuteries
  previewing = $state<string | null>(null);

  // Voix préférées (♥) : tant que l'utilisateur n'a rien changé (null), ce sont les voix recommandées
  likedIds = $state<string[] | null>(store.get<string[]>('liked'));
  recommendedAll = $derived([...(this.catalog.recommended.fr ?? []), ...(this.catalog.recommended.en ?? [])]);
  liked = $derived<string[]>(this.likedIds ?? [...new Set(this.recommendedAll.map((r) => r.id))]);

  voices = $derived<Voice[]>([...this.catalog.custom.map((v) => ({ ...v, custom: true })), ...this.catalog.builtin]);
  likedVoices = $derived<Voice[]>(
    this.liked.map((id) => this.voices.find((v) => v.id === id)).filter((v): v is Voice => v !== undefined),
  );
  voiceId = $derived<string | undefined>(this.selectedVoice[this.lang]);
  voice = $derived<Voice | undefined>(this.voices.find((v) => v.id === this.voiceId));
  openBook = $derived<Book | undefined>(this.books.find((b) => b.id === this.openId));

  private pollTimer: ReturnType<typeof setTimeout> | undefined;
  private nextTaskId = 1;
  private previewAudio = new Audio();

  voiceById = (id: string | undefined): Voice | undefined => this.voices.find((v) => v.id === id);

  /** Exécute `work` en la montrant dans la barre d'état tant qu'elle dure. */
  async track<T>(task: Omit<LocalTask, 'id' | 'since'>, work: (live: LocalTask) => Promise<T>): Promise<T> {
    const id = this.nextTaskId++;
    this.localTasks.push({ ...task, id, since: Date.now() });
    const live = this.localTasks[this.localTasks.length - 1]; // version réactive : `live.percent = …` met la barre à jour
    try {
      return await work(live);
    } finally {
      this.localTasks = this.localTasks.filter((x) => x.id !== id);
    }
  }

  /** Annule une conversion en attente ou en cours : le livre redevient un brouillon (ou reste « prêt »). */
  async cancelConversion(b: Book): Promise<void> {
    if (b.status === 'processing' && !confirm(`Annuler la conversion de « ${b.title} » ? La progression sera perdue.`)) return;
    try {
      await api<Book>(`/api/books/${b.id}/cancel`, { method: 'POST' });
    } catch (e) {
      alert(errorMessage(e));
    }
    await this.refreshBooks();
  }

  isLiked = (id: string): boolean => this.liked.includes(id);

  toggleLike(id: string): void {
    this.likedIds = this.isLiked(id) ? this.liked.filter((x) => x !== id) : [...this.liked, id];
    store.set('liked', $state.snapshot(this.likedIds));
  }

  /** Courte description d'une voix recommandée (« Femme · posée ») ou d'une voix créée (clonée, mélangée). */
  descOf(id: string): string {
    return this.recommendedAll.find((r) => r.id === id)?.desc ?? this.catalog.custom.find((v) => v.id === id)?.info ?? '';
  }

  async init(): Promise<void> {
    for (;;) {
      try {
        this.config = await api<Config>('/api/config');
        break;
      } catch {
        await sleep(2000);
      }
    }
    const cfg = this.config!;
    this.lang = store.get<Lang>('lang') ?? (navigator.language?.startsWith('fr') ? 'fr' : 'en');
    this.selectedVoice = store.get<Partial<Record<Lang, string>>>('voices') ?? {};
    this.mode = store.get<string>('mode') === 'chapters' ? 'chapters' : 'single';
    this.settings = { ...cfg.defaults, ...(store.get<Partial<Settings>>('settings') ?? {}) };
    setInterval(() => (this.now = Date.now()), 1000);
    await this.refreshBooks();
    // Lien direct vers un livre (#livre=<id>) : un rechargement garde le livre ouvert
    const m = initialHash.match(/^#livre=([0-9a-f]+)$/);
    if (m && this.books.some((b) => b.id === m[1])) this.openId = m[1];
    // Le catalogue attend le chargement du modèle (~30 s après un redémarrage)
    for (;;) {
      try {
        await this.loadVoices();
        break;
      } catch {
        await sleep(3000);
      }
    }
  }

  // --- Voix ---
  async loadVoices(): Promise<void> {
    this.catalog = await api<Catalog>('/api/voices');
    this.catalogReady = true;
    this.ensureVoice();
  }

  /** Garde toujours une voix valide pour la langue courante (la première recommandée sinon). */
  private ensureVoice(): void {
    if (!this.voiceById(this.selectedVoice[this.lang])) {
      this.selectedVoice[this.lang] = this.catalog.recommended[this.lang]?.[0]?.id;
    }
  }

  setLang(l: Lang): void {
    this.lang = l;
    store.set('lang', l);
    this.ensureVoice();
  }

  selectVoice(id: string): void {
    this.selectedVoice[this.lang] = id;
    store.set('voices', $state.snapshot(this.selectedVoice));
  }

  async deleteVoice(id: string): Promise<void> {
    await fetch(`/api/voices/${id}`, { method: 'DELETE' });
    await this.loadVoices();
  }

  /** Après un clonage ou un mélange : la nouvelle voix est sélectionnée. */
  async voiceCreated(v: Voice): Promise<void> {
    this.selectVoice(v.id);
    await this.loadVoices();
  }

  async preview(id: string, text = ''): Promise<void> {
    const params = new URLSearchParams({ lang: this.lang, speed: String(this.speed), settings: JSON.stringify(this.settings) });
    if (text) params.set('text', text);
    this.previewing = id;
    this.previewAudio.pause();
    this.previewAudio.src = `/api/voices/${id}/preview?${params}`;
    try {
      await this.track({ icon: '🔈', title: this.voiceById(id)?.name ?? id, label: "Génération d'un extrait de voix…" }, () =>
        this.previewAudio.play());
    } catch {
      alert("Impossible de générer l'extrait.");
    } finally {
      this.previewing = null;
    }
  }

  // --- Réglages ---
  setMode(m: Mode): void {
    this.mode = m;
    store.set('mode', m);
  }

  setSetting(key: keyof Settings, value: number): void {
    this.settings[key] = value;
    store.set('settings', $state.snapshot(this.settings));
  }

  resetSettings(): void {
    this.settings = { ...this.config!.defaults };
    this.speed = DEFAULT_SPEED;
    store.set('settings', $state.snapshot(this.settings));
  }

  /** Voix, langue, vitesse et réglages de la barre de gauche (échantillon et conversion d'un brouillon). */
  choice() {
    return { voice: this.voiceId, language: this.lang, speed: this.speed, settings: $state.snapshot(this.settings) };
  }

  // --- Bibliothèque ---
  async refreshBooks(): Promise<void> {
    try {
      this.books = await api<Book[]>('/api/books');
    } catch {
      return;
    }
    if (this.openId && !this.books.some((b) => b.id === this.openId)) this.openId = null;
    clearTimeout(this.pollTimer);
    const busy = (b: Book) =>
      b.status === 'queued' || b.status === 'processing' ||
      Object.values(b.exports ?? {}).some((x) => x?.status === 'pending' || x?.status === 'working');
    if (this.books.some(busy)) this.pollTimer = setTimeout(() => this.refreshBooks(), 2000);
  }

  async deleteBook(b: Book): Promise<void> {
    const warn = b.status === 'processing' ? ' La conversion en cours sera arrêtée.' : '';
    if (!confirm(`Supprimer « ${b.title} » ?${warn}`)) return;
    await fetch(`/api/books/${b.id}`, { method: 'DELETE' });
    await this.refreshBooks();
  }

  // --- Envoi de documents ---
  /** Un fichier : on ouvre directement le livre pour l'échantillon. Plusieurs : on reste dans la bibliothèque. */
  async uploadFiles(files: File[]): Promise<void> {
    if (!files.length) return;
    if (!this.voiceId) {
      this.uploadMsg = { text: "Choisissez d'abord une voix (barre de gauche).", error: true };
      return;
    }
    const added: Book[] = [];
    for (const f of files) {
      const b = await this.uploadOne(f);
      if (b) added.push(b);
    }
    if (files.length > 1) {
      this.uploadMsg = {
        text: `${added.length} livre(s) ajouté(s) sur ${files.length}. Ouvrez-les pour écouter un échantillon et lancer la conversion.`,
        error: added.length < files.length,
      };
    } else if (added.length) {
      this.openId = added[0].id;
    }
  }

  private async uploadOne(file: File): Promise<Book | null> {
    const fd = form({
      voice: this.voiceId!, language: this.lang, speed: this.speed, mode: this.mode,
      settings: JSON.stringify(this.settings),
    });
    fd.append('file', file);
    this.uploadMsg = { text: `Extraction du texte de « ${file.name} »…`, error: false };
    try {
      const book = await this.track({ icon: '⏳', title: file.name, label: 'Extraction du texte…' }, () =>
        api<Book>('/api/books', { method: 'POST', body: fd }));
      let text = `« ${book.title} » ajouté : ${book.chars.toLocaleString('fr')} caractères, ${book.chapter_count} chapitres détectés. `
        + "Rien n'est converti pour l'instant : écoutez un échantillon, ajustez la voix et les réglages (barre de gauche), puis lancez la conversion.";
      if (book.detected_language !== book.language) {
        text += ` ⚠ Le texte semble être en ${LANG_NAMES[book.detected_language]} : choisissez la bonne langue dans la barre de gauche.`;
      }
      this.uploadMsg = { text, error: false };
      return book;
    } catch (e) {
      this.uploadMsg = { text: `« ${file.name} » : ${errorMessage(e)}`, error: true };
      return null;
    } finally {
      await this.refreshBooks();
    }
  }
}

export const app = new App();
