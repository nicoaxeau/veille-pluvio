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
| `moteur.py` | détection et machine à états, sur `pluie.json`. Lecture seule, sortie JSON sur stdout |
| `test_moteur.py` | contrôle du moteur, dont la simulation sur la référence |
| `sequences-reference.json` | les 236 séquences attendues sur `pluie-reference.json` |
| `maj_etat.py` | écrit `etat.json` à partir de la sortie du moteur |
| `verif_etat.py` | garde-fou : refuse le commit si `etat.json`, `pluie.json` ou `stations.json` contient une adresse |
| `test_coherence.py` | non-régression entre `moteur.py` et `index.html` |
| `index.html` | la page de suivi, servie par GitHub Pages |
| `etat.json` | états et compteurs agrégés. Jamais de détail par destinataire |
| `depts.json`, `libelles-departements.json` | données de référence des 96 départements |
| `stations.json` | la liste figée des 96 stations Météo-France, une par département |
| `test_stations.py` | contrôle de `stations.json` |
| `extraction_meteofrance.py` | télécharge les fichiers Météo-France et produit `pluie.json` |
| `pluie.json` | la pluie quotidienne des 96 stations sur 400 jours, avec la source et la mention |
| `pluie-reference.json` | la même extraction, figée sur les fichiers du 06/10/2026, pour les tests |
| `test_extraction.py` | contrôle de l'extraction et de la référence |

## La station de chaque département

Le passage aux observations de Météo-France est en cours, sur la branche
`meteofrance`. L'extraction lit `stations.json` et produit `pluie.json`, que lit
le moteur ; la page n'utilise pas encore Météo-France.

Chaque département a **une station** : la station Météo-France la plus proche
de la préfecture, **dans le département**, qui mesure la pluie. Le mail ne doit
jamais citer une mesure prise ailleurs.

La liste est **figée** : elle n'est jamais recalculée. Une station silencieuse
3 jours de suite déclenchera une alerte ; la remplacer est un commit relu, qui
renseigne le champ `remplace` (numéro, nom et motif de l'ancienne station).

`test_stations.py` vérifie la liste : 96 stations, une par département, chacune
dans son département (en Corse, par le numéro de commune), à moins de 15 km de
la préfecture, sous 1 000 m d'altitude, sans aucune adresse email.

## Les données Météo-France

`extraction_meteofrance.py` produit `pluie.json` : la pluie quotidienne des 96
stations de `stations.json`, sur les 400 derniers jours.

- **Source** : Météo-France, « Données climatologiques de base - quotidiennes »,
  [data.gouv.fr](https://www.data.gouv.fr/datasets/donnees-climatologiques-de-base-quotidiennes),
  Licence Ouverte 2.0. La licence impose de citer la source et la date de mise
  à jour : `pluie.json` porte la mention à reprendre, par exemple
  « Données pluviométriques : Météo-France, mise à jour du 6 octobre 2026 ».
- **Journée Météo-France** : de 06 h UTC le jour J à 06 h UTC le jour J+1. Les
  dates sont reprises telles quelles, sans conversion.
- **Un jour sans donnée est écrit `null`, jamais 0** : c'est une erreur, pas un
  jour sec.
- Pour chaque station : l'état du fichier de son département (`a_jour`,
  `en_retard`, `absent`), sa date de publication, son dernier jour de pluie
  publié, et le nombre de jours de silence de la station. À partir de 3 jours,
  l'extraction signale la station.
- L'adresse des fichiers est trouvée à chaque tour par l'API de data.gouv.fr :
  leur nom porte les années, et changera en janvier.

Le moteur lit `pluie.json`. Un jour `null` ne déclenche rien, ne compte pas
comme jour de pluie, et met le département en erreur pour la journée. La
phrase de série A cite le jour le plus fort de l'épisode, déjà connu au mail 1
(J+5), arrondi au millimètre, la demie vers le haut : « Le 30 septembre, 146 mm
de pluie sont tombés en 24 heures dans l'Hérault. » Au-delà de 20 départements
sans la donnée du jour, `maj_etat.py` ne publie pas.

`pluie-reference.json` est la même extraction, figée sur les fichiers publiés
le 06/10/2026. Les tests s'appuient dessus ; elle ne change jamais.

`test_extraction.py` vérifie l'extraction sur des fichiers fabriqués (valeur
vide, ligne manquante, fichier en retard, absent ou illisible, station muette)
et la référence, sur des valeurs relevées à la main dans les fichiers bruts.

## Deux implémentations, un seul texte

La détection existe en Python dans `moteur.py` et en JavaScript dans
`index.html` — la page recalcule tout côté navigateur pour rester lisible
sans serveur.

**Toute modification de l'une doit être reportée sur l'autre.**
`test_coherence.py` compare les quatre phrases produites de chaque côté,
interpolations normalisées, et échoue si elles divergent d'un caractère. Le
workflow le lance avant toute publication d'état.

## La bascule en mode réel

`etat.json` porte un champ `bascule`, à `null` tant que le cron tourne à blanc.

Quand il sera posé à une date, **tout déclencheur dont le mail 1 était dû avant
cette date est marqué `abandonne`**, jamais `a_monter` : écrire à propos d'un
orage vieux de deux semaines n'a pas de sens.

L'abandon **n'arme aucun verrou**. Le prochain épisode réel de ces départements
repart donc normalement, sans attendre les 51 jours du cycle.

`moteur.py` et `index.html` lisent la même valeur dans le même fichier — une
seule source de vérité, sans quoi les deux implémentations divergeraient dès le
premier jour. `maj_etat.py` affiche combien de déclencheurs ont été abandonnés
et lesquels.

## La tâche planifiée

`.github/workflows/veille.yml`, tous les jours à 11 h de Paris.

Elle tourne **à blanc** : elle détecte, elle écrit `etat.json`, et c'est tout.
Aucun mail n'est monté, programmé ni envoyé depuis ce dépôt, et aucun secret
n'y est déclaré.

Un échec ouvre une issue étiquetée `veille-echec`. La page continue d'afficher
le dernier état publié.
