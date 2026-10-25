import { api, apiText, form } from './api';
import { app } from './store.svelte';
import { store } from './storage';
import type { Book, Chapter, ExportKind, Lang, SampleInfo, SampleJob, VersionInfo } from './types';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Numéro du chapitre qui contient le paragraphe `para`. */
export function chapterAt(para: number, list: Chapter[]): number {
  let k = 0;
  for (let i = 0; i < list.length; i++) if (list[i].start <= para) k = i;
  return k;
}

/** Tout ce qui concerne un livre ouvert : texte, chapitres, échantillon, lecture, exports. */
export class BookSession {
  readonly id: string;
  book = $state<Book | null>(null);
  paragraphs = $state.raw<string[]>([]);
  timings = $state.raw<number[]>([]);        // début (secondes) de chaque paragraphe, une fois converti
  chapters = $state<Chapter[]>([]);
  editChapters = $state<Chapter[] | null>(null);   // copie en cours de modification (null = lecture)
  sampleSel = $state<number[]>([]);                // paragraphes cochés pour l'échantillon (vide = les 2 premiers)
  curPara = $state(-1);                            // paragraphe lu en ce moment
  follow = $state(true);
  ready = $state(false);
  scrollRequest = $state<{ index: number } | null>(null);
  audio: HTMLAudioElement | null = null;

  shownChapters = $derived(this.editChapters ?? this.chapters);
  curChapter = $derived(this.chapters.length && this.curPara >= 0 ? chapterAt(this.curPara, this.chapters) : -1);
  busy = $derived(this.book?.status === 'queued' || this.book?.status === 'processing');

  samples = $state<SampleInfo[]>([]);              // échantillons conservés (plus récent d'abord)
  versions = $state<VersionInfo[]>([]);            // conversions précédentes conservées
  lastSampleId = $state<string | null>(null);      // dernier échantillon créé : il se lance tout seul
  sampleProgress = $state<number | null>(null);    // avancement (0-100) de l'échantillon en cours
  private sampleJob: { id: string; cancelled: boolean } | null = null;
  private lastSave = 0;
  private lastPicked = -1;

  constructor(id: string) {
    this.id = id;
  }

  async load(): Promise<void> {
    const book = await api<Book>(`/api/books/${this.id}`);
    this.book = book;
    this.paragraphs = (await apiText(`/api/books/${this.id}/text`)).split('\n\n');
    this.timings = book.status === 'done' ? await api<number[]>(`/api/books/${this.id}/timings`) : [];
    this.chapters = await api<Chapter[]>(`/api/books/${this.id}/chapters`);
    this.editChapters = book.status === 'draft' ? $state.snapshot(this.chapters) : null;
    this.curPara = -1;
    await Promise.all([this.loadSamples(), this.loadVersions()]);
    this.ready = true;
  }

  async loadSamples(): Promise<void> {
    this.samples = await api<SampleInfo[]>(`/api/books/${this.id}/samples`);
  }

  async loadVersions(): Promise<void> {
    this.versions = await api<VersionInfo[]>(`/api/books/${this.id}/versions`);
  }

  async deleteSample(id: string): Promise<void> {
    await fetch(`/api/books/${this.id}/samples/${id}`, { method: 'DELETE' });
    await this.loadSamples();
  }

  async deleteVersion(id: string): Promise<void> {
    await fetch(`/api/books/${this.id}/versions/${id}`, { method: 'DELETE' });
    await this.loadVersions();
  }

  /** Met à jour l'état depuis la liste des livres (sondage) ; recharge tout quand la conversion se termine. */
  async sync(b: Book): Promise<void> {
    if (!this.book) return;
    if (b.status === 'done' && this.book.status !== 'done') await this.load();
    else this.book = { ...this.book, ...b };
  }

  // --- Chapitres ---
  startEdit(): void {
    this.editChapters = $state.snapshot(this.chapters);
  }

  cancelEdit(): void {
    this.editChapters = null;
  }

  async saveChapters(): Promise<void> {
    if (!this.editChapters) return;
    this.chapters = await api<Chapter[]>(`/api/books/${this.id}/chapters`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.editChapters.map(({ title, start, include }) => ({ title, start, include }))),
    });
  }

  async commitEdit(): Promise<void> {
    await this.saveChapters();
    this.editChapters = null;
    await app.refreshBooks();
  }

  /** Fait commencer (ou retire) un chapitre au paragraphe `i`. */
  toggleChapterStart(i: number): void {
    const list = this.editChapters;
    if (!list) return;
    const k = list.findIndex((c) => c.start === i);
    if (k === 0) return; // le premier chapitre commence toujours au début
    if (k > 0) list.splice(k, 1);
    else {
      list.push({ title: this.paragraphs[i].slice(0, 60), start: i, include: true });
      list.sort((a, b) => a.start - b.start);
    }
  }

  removeChapter(k: number): void {
    this.editChapters?.splice(k, 1);
  }

  // --- Lecture ---
  seekParagraph(i: number): void {
    if (!this.timings.length || !this.audio) return;
    this.audio.currentTime = this.timings[i] + 0.01;
    void this.audio.play();
  }

  openChapter(c: Chapter): void {
    if (this.timings.length) this.seekParagraph(c.start);
    else this.scrollRequest = { index: c.start };
  }

  onTimeUpdate(): void {
    const audio = this.audio;
    if (!audio) return;
    if (Date.now() - this.lastSave > 5000) {
      this.savePosition();
      this.lastSave = Date.now();
    }
    const t = this.timings;
    if (!t.length) return;
    let lo = 0, hi = t.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (t[mid] <= audio.currentTime) lo = mid;
      else hi = mid - 1;
    }
    if (lo !== this.curPara) this.curPara = lo;
  }

  savePosition(): void {
    if (this.book?.status === 'done' && this.audio && this.audio.currentTime > 0) {
      store.set(`pos:${this.id}`, this.audio.currentTime);
    }
  }

  restorePosition(): void {
    const pos = store.get<number>(`pos:${this.id}`);
    if (pos && this.audio) this.audio.currentTime = pos;
  }

  // --- Échantillon et conversion (réglages de la barre de gauche) ---
  /** Coche / décoche un paragraphe pour l'échantillon ; avec `range` (Maj+clic), toute la plage depuis le dernier coché. */
  toggleSample(i: number, range = false): void {
    const set = new Set(this.sampleSel);
    if (range && this.lastPicked >= 0) {
      const turnOn = !set.has(i);
      for (let k = Math.min(this.lastPicked, i); k <= Math.max(this.lastPicked, i); k++) {
        if (turnOn) set.add(k);
        else set.delete(k);
      }
    } else if (set.has(i)) set.delete(i);
    else set.add(i);
    this.lastPicked = i;
    this.sampleSel = [...set].sort((a, b) => a - b);
  }

  clearSample(): void {
    this.sampleSel = [];
    this.lastPicked = -1;
  }

  /** Génère l'échantillon (tâche de fond suivie en %), le conserve, et renvoie son identifiant (null s'il est annulé). */
  async makeSample(): Promise<string | null> {
    const c = app.choice();
    if (!c.voice) throw new Error("Choisissez d'abord une voix.");
    await this.saveChapters(); // les chapitres décochés sont ignorés par l'échantillon
    const n = this.sampleSel.length || 2;
    const job = { id: '', cancelled: false };
    this.sampleJob = job;
    this.sampleProgress = 0;
    const base = `/api/books/${this.id}/sample`;
    try {
      return await app.track(
        {
          icon: '🎧', title: this.book?.title ?? 'Livre', bookId: this.id, percent: 0,
          label: `Échantillon (${n} paragraphe${n > 1 ? 's' : ''})`, cancel: () => void this.cancelSample(),
        },
        async (live) => {
          const started = await api<SampleJob>(base, {
            method: 'POST',
            body: form({ voice: c.voice!, lang: c.language, speed: c.speed, settings: JSON.stringify(c.settings), sel: this.sampleSel.join(',') }),
          });
          job.id = started.id;
          if (job.cancelled) {
            await fetch(`${base}/jobs/${job.id}`, { method: 'DELETE' }).catch(() => {});
            return null;
          }
          let finished: string | null = null;
          for (;;) {
            const st = await api<SampleJob>(`${base}/jobs/${job.id}`);
            if (job.cancelled || st.status === 'cancelled') return null;
            if (st.status === 'error') throw new Error(st.error ?? "Échec de l'échantillon");
            live.percent = this.sampleProgress = Math.round(st.progress * 100);
            if (st.status === 'done') {
              finished = st.sample;
              break;
            }
            await sleep(300);
          }
          await this.loadSamples();
          this.lastSampleId = finished;
          return finished;
        },
      );
    } finally {
      this.sampleProgress = null;
      if (this.sampleJob === job) this.sampleJob = null;
    }
  }

  /** Arrête l'échantillon en cours (le serveur s'arrête à la prochaine phrase). */
  async cancelSample(): Promise<void> {
    const job = this.sampleJob;
    if (!job) return;
    job.cancelled = true;
    if (job.id) await fetch(`/api/books/${this.id}/sample/jobs/${job.id}`, { method: 'DELETE' }).catch(() => {});
  }
  async startConversion(): Promise<void> {
    const c = app.choice();
    if (!c.voice) throw new Error("Choisissez d'abord une voix.");
    await this.saveChapters();
    this.editChapters = null;
    this.book = await api<Book>(`/api/books/${this.id}/start`, {
      method: 'POST',
      body: form({ voice: c.voice, language: c.language, speed: c.speed, settings: JSON.stringify(c.settings) }),
    });
    void app.refreshBooks();
  }

  async regenerate(voice: string, language: Lang): Promise<void> {
    this.audio?.pause();
    this.book = await api<Book>(`/api/books/${this.id}/regenerate`, {
      method: 'POST',
      body: form({ voice, language, speed: app.speed, settings: JSON.stringify(app.settings) }),
    });
    this.timings = [];
    void app.refreshBooks();
  }

  async requestExport(kind: ExportKind): Promise<void> {
    await api(`/api/books/${this.id}/export/${kind}`, { method: 'POST' });
    void app.refreshBooks();
  }
}
