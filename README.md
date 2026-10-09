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

Source des données : les observations quotidiennes de Météo-France, une
station par département, publiées sur data.gouv.fr sous Licence Ouverte 2.0.
Voir « Les données Météo-France » plus bas.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `moteur.py` | détection et machine à états, sur `pluie.json`. Lecture seule, sortie JSON sur stdout |
| `test_moteur.py` | contrôle du moteur, dont la simulation sur la référence |
| `sequences-reference.json` | les 236 séquences attendues sur `pluie-reference.json` |
| `maj_etat.py` | écrit `etat.json` à partir de la sortie du moteur |
| `verif_etat.py` | garde-fou : refuse le commit si `etat.json`, `pluie.json` ou `stations.json` contient une adresse |
| `test_coherence.py` | non-régression entre `moteur.py` et la page (`detection.js`), à l'unité |
| `index.html` | la page de suivi, servie par GitHub Pages. Lit `pluie.json`, `stations.json` et `etat.json` sur le site lui-même |
| `detection.js` | le calcul de la page, réplique exacte de `moteur.py` |
| `etat.json` | états et compteurs agrégés. Jamais de détail par destinataire |
| `depts.json`, `libelles-departements.json` | données de référence des 96 départements |
| `stations.json` | la liste figée des 96 stations Météo-France, une par département |
| `test_stations.py` | contrôle de `stations.json` |
| `extraction_meteofrance.py` | télécharge les fichiers Météo-France et produit `pluie.json` |
| `pluie.json` | la pluie quotidienne des 96 stations sur 400 jours, avec la source et la mention |
| `pluie-reference.json` | la même extraction, figée sur les fichiers du 06/10/2026, pour les tests |
| `test_extraction.py` | contrôle de l'extraction et de la référence |
| `rappels.py`, `rappels.xml` | le flux RSS des brouillons prêts et pas encore envoyés (date d'envoi, lien Mailjet), lu chaque matin par un flux Power Automate qui envoie le rappel. Aucune adresse ; régénéré à chaque écriture de `etat.json` |

## La station de chaque département

Depuis le 08/10/2026, la veille repose sur les observations de Météo-France.
L'extraction lit `stations.json` et produit `pluie.json`, que
lisent le moteur et la page.

Chaque département a **une station** : la station Météo-France la plus proche
de la préfecture, **dans le département**, qui mesure la pluie. Le mail ne doit
jamais citer une mesure prise ailleurs.

La liste est **figée** : elle n'est jamais recalculée. Une station silencieuse
3 jours de suite déclenche une alerte : une issue « Station Meteo-France
muette », une par station, commentée chaque jour tant qu'elle se tait. La
remplacer est un commit relu, qui renseigne le champ `remplace` (numéro, nom
et motif de l'ancienne station).

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
  l'extraction signale la station, et le workflow ouvre une issue.
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
`detection.js`, que charge `index.html` — la page recalcule tout côté
navigateur pour rester lisible sans serveur. `detection.js` ne touche ni à la
page ni au réseau : des fonctions pures, que les tests peuvent faire tourner
hors navigateur.

**Toute modification de l'une doit être reportée sur l'autre.**
`test_coherence.py` fait tourner `detection.js` (sous Node sur GitHub, dans
Chrome sans fenêtre en local) et `moteur.py` sur les mêmes données : cas
fabriqués, `pluie-reference.json`, le moteur lancé comme par le workflow à deux
dates, et le `pluie.json` du jour. Il exige le même résultat à l'unité :
déclencheurs, jours cités, lignes, étapes, phrases, mentions, et la simulation
de douze mois (236 séquences, 472 campagnes sur la référence). Sur GitHub,
l'absence de Node le fait échouer. Le workflow le lance avant toute publication
d'état.

La page appelle `detection.js?v=` suivi de l'empreinte du fichier : sans quoi
un navigateur peut garder l'ancien calcul en cache avec la nouvelle page.
**Toute modification de `detection.js` doit changer cette empreinte dans
`index.html`** ; `test_coherence.py` le vérifie et donne la bonne valeur.

La page ouvre ses données par `fetch` : elle doit être servie par un serveur
web. Un double-clic sur `index.html` ne permet pas de lire les fichiers. En
local : `python -m http.server 8000 --bind 127.0.0.1` dans ce dossier, puis
`http://127.0.0.1:8000` dans le navigateur.

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

`.github/workflows/veille.yml`, tous les jours à 9 h 17 UTC (11 h 17 de Paris en été, 10 h 17 en hiver, sans rien changer au changement d'heure), au plus tôt :
GitHub retarde les tâches planifiées de plusieurs heures.

Elle tourne **à blanc** : elle télécharge, elle détecte, elle écrit
`pluie.json` et `etat.json`, et c'est tout. Aucun mail n'est monté, programmé
ni envoyé depuis ce dépôt, et aucun secret n'y est déclaré.

Le tour, dans l'ordre :

1. les tests hors ligne : `test_stations.py`, `test_extraction.py`,
   `test_moteur.py` ;
2. le téléchargement des 95 fichiers Météo-France, trois essais chacun,
   8 minutes au plus ;
3. la liste des stations muettes depuis 3 jours ou plus ;
4. le moteur ;
5. `test_coherence.py`, qui compare la page et le moteur, sur la référence et
   sur les données du jour ;
6. `maj_etat.py`, puis le contrôle anti-adresse `verif_etat.py` ;
7. le commit de `pluie.json` et de `etat.json`.

Un fichier pas encore republié ce matin met ses départements « en retard » :
le jour manque, il compte en erreur, jamais comme sec, et le tour du lendemain
rattrape. Au-delà de 20 départements sans la donnée du jour, le tour échoue.

Après chaque tour, quel qu'en soit le résultat, le job `alertes`, seul autorisé
à écrire des issues, ouvre :

- une issue `veille-echec` si le tour a échoué ou a été annulé ; tant qu'elle
  est ouverte, les échecs suivants la commentent ;
- une issue `station-muette` par station silencieuse depuis 3 jours ou plus,
  commentée chaque jour tant qu'elle se tait, jamais dupliquée.

Il refuse d'ouvrir une issue dont le texte contiendrait une adresse. La page
continue d'afficher le dernier état publié.
