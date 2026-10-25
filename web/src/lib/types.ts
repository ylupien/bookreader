// Formes des données de l'API (server/main.py)
export type Lang = 'fr' | 'en';
export type Mode = 'single' | 'chapters';
export type Status = 'draft' | 'queued' | 'processing' | 'done' | 'error';

export interface Settings {
  temperature: number;
  top_p: number;
  repetition_penalty: number;
  sentence_pause: number;
  paragraph_pause: number;
}

export interface Config {
  device: string;
  formats: string[];
  defaults: Settings;
  limits: Record<keyof Settings, [number, number]>;
}

export interface ExportInfo {
  status: 'pending' | 'working' | 'ready' | 'error';
  progress?: number;
  error?: string | null;
  size?: number;
}

export type ExportKind = 'zip' | 'm4b';

export interface Book {
  id: string;
  title: string;
  filename: string | null;
  voice: string;
  voice_name: string;
  language: Lang;
  detected_language: Lang;
  speed: number;
  settings: Settings;
  mode: Mode;
  chapter_count: number;
  chars: number;
  status: Status;
  progress: number;
  created: number;
  started_at?: number | null;
  finished_at?: number | null;
  duration?: number;
  error: string | null;
  exports?: Partial<Record<ExportKind, ExportInfo>>;
  export_rev?: number;
}

export interface Chapter {
  title: string;
  start: number;
  include: boolean;
  time?: number;
  length?: number;
}

export interface Voice {
  id: string;
  name: string;
  info?: string;
  custom?: boolean;
}

/** Tâche de fond du serveur : génération d'un échantillon. */
export interface SampleJob {
  id: string;
  status: 'working' | 'done' | 'error' | 'cancelled';
  progress: number;
  error: string | null;
  sample: string | null;   // identifiant de l'échantillon conservé, une fois terminé
}

/** Échantillon conservé avec ses métadonnées (samples/<id>.wav + .json). */
export interface SampleInfo {
  id: string;
  created: number;
  voice?: string;
  voice_name?: string;
  language?: Lang;
  speed?: number;
  settings?: Settings;
  paragraphs?: number[];   // numéros (à partir de 0) des paragraphes lus
  chars?: number;
  duration?: number;
  size?: number;
}

/** Conversion précédente conservée (versions/<id>/ : audio, exports, minutages, chapitres + métadonnées). */
export interface VersionInfo {
  id: string;
  title?: string;
  created: number;
  voice_name?: string;
  language?: Lang;
  speed?: number;
  settings?: Settings;
  mode?: Mode;
  duration?: number;
  paragraphs?: number;
  size?: number;
  exports?: Partial<Record<ExportKind, number>>;   // taille des exports conservés
}

export interface Catalog {
  recommended: Record<Lang, { id: string; desc: string }[]>;
  builtin: Voice[];
  custom: Voice[];
}
