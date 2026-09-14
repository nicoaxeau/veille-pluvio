# Veille pluviométrique Ax'eau

Détection quotidienne des épisodes pluvieux par département métropolitain, et
page de suivi.

## Ce dépôt est public

**Aucune adresse email ne doit y figurer**, nulle part, y compris dans un champ
technique de `etat.json` ou dans les logs d'une exécution.

Deux mécanismes le garantissent :

- `.gitignore` est une **liste blanche** : tout est exclu par défaut, seuls les
  fichiers qui y sont nommés entrent dans le dépôt. Ajouter un fichier au
  projet ne le publie pas.
- `verif_etat.py` s'exécute **avant chaque commit de `etat.json`** dans le
  workflow. Il refuse toute chaîne contenant un `@` suivi d'un point, à quelque
  profondeur que ce soit, clés de dictionnaire comprises, et tout champ dont le
  nom évoque un destinataire. S'il en trouve, le workflow échoue et ne commite
  pas.

## La règle métier

Deux déclencheurs indépendants, calculés par département sur les 96 de
métropole :

| Série | Condition |
|---|---|
| **A** — intensité | un jour à **≥ 30 mm** en 24 h |
| **B** — persistance | **≥ 15 jours de pluie** (≥ 1 mm) sur 30 jours glissants |

Source des données : [Open-Meteo](https://open-meteo.com/), API publique en
lecture, sans identifiant.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `moteur.py` | détection et machine à états. Lecture seule, sortie JSON sur stdout |
| `maj_etat.py` | écrit `etat.json` à partir de la sortie du moteur |
| `verif_etat.py` | garde-fou : refuse le commit si `etat.json` contient une adresse |
| `test_coherence.py` | non-régression entre `moteur.py` et `index.html` |
| `index.html` | la page de suivi, servie par GitHub Pages |
| `etat.json` | états et compteurs agrégés. Jamais de détail par destinataire |
| `depts.json`, `libelles-departements.json` | données de référence des 96 départements |

## Deux implémentations, un seul texte

La détection existe en Python dans `moteur.py` et en JavaScript dans
`index.html` — la page recalcule tout côté navigateur pour rester lisible
sans serveur.

**Toute modification de l'une doit être reportée sur l'autre.**
`test_coherence.py` compare les quatre phrases produites de chaque côté,
interpolations normalisées, et échoue si elles divergent d'un caractère. Le
workflow le lance avant toute publication d'état.

## La tâche planifiée

`.github/workflows/veille.yml`, tous les jours à 11 h de Paris.

Elle tourne **à blanc** : elle détecte, elle écrit `etat.json`, et c'est tout.
Aucun mail n'est monté, programmé ni envoyé depuis ce dépôt, et aucun secret
n'y est déclaré.

Un échec ouvre une issue étiquetée `veille-echec`. La page continue d'afficher
le dernier état publié.
