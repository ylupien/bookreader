# BookReader

Convertit un document (PDF, TXT, MD, DOCX, EPUB, HTML, RTF) en livre audio MP3, en français ou en anglais, avec des voix neuronales naturelles (XTTS-v2, sur GPU NVIDIA).

## Lancer

```bash
docker compose up -d --build
```

Puis ouvrir http://localhost:8000 (le modèle met ~30 s à se charger au démarrage).

Les livres sont conservés dans `./data`.

## Voix

- **Recommandées** : Ana, Claribel, Damien (FR) · Claribel, Daisy, Andrew (EN).
- **Toutes les voix intégrées** : 58 locuteurs XTTS-v2, chacun peut lire en français et en anglais.
- **Créer une voix** :
  - *Cloner* : 10 à 30 s d'enregistrement (fichier ou micro directement dans la page).
  - *Mélanger* : combinaison de deux voix existantes, proportion réglable.
  Les voix créées sont stockées dans `data/voices`.

## Réglages avancés

| Réglage | Défaut | Effet |
|---|---|---|
| Vitesse | 0.9 | Rythme de lecture (0.7 à 1.3) |
| Expressivité (température) | 0.75 | Bas : stable/monotone · Haut : vivant, risque d'artefacts |
| Variété de l'intonation (top-p) | 0.85 | Bas : prévisible · Haut : plus de variations |
| Anti-répétition | 5.0 | À augmenter si la voix bégaie |
| Pause entre phrases | 0.25 s | Silence après chaque phrase |
| Pause entre paragraphes | 0.8 s | Silence après chaque paragraphe |

Le bouton « Essayer ces réglages » génère un extrait avec la voix et les réglages choisis.

## Chapitres

- **Format « Un fichier par chapitre »** : les chapitres sont détectés à l'upload, puis vérifiés avant la conversion
  (renommer, décocher les parties à ignorer comme la table des matières, ajouter ou retirer un découpage en cliquant dans le texte).
  Les parties décochées ne sont pas synthétisées.
- **Détection** : table des matières (EPUB), styles de titre (DOCX), `#` (Markdown), `<h1>`/`<h2>` (HTML), signets (PDF) ;
  sinon table des matières retrouvée dans le texte, titres « Chapitre 3 », « Prologue »… ; sinon parties d'environ 25 min.
- **Exports** : ZIP d'un MP3 par chapitre (tags titre, album, piste + playlist .m3u) et M4B avec marqueurs de chapitres.
  Disponibles aussi pour les livres en fichier unique (bouton « Préparer »). Le découpage se fait sans réencoder l'audio.

## Notes

- Nécessite un GPU NVIDIA (fonctionne aussi sur CPU, mais très lentement).
- Licence du modèle XTTS-v2 : Coqui Public Model License, **usage non commercial seulement**.
- Ne clonez une voix qu'avec l'accord de la personne.
- Les PDF scannés (images) ne contiennent pas de texte : un OCR serait nécessaire.
- Vitesse de lecture par défaut : 0.9× (réglable de 0.7× à 1.3×).
