#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extraction des observations Meteo-France pour les 96 stations de la liste
figee, stations.json. Produit pluie.json, que liront le moteur et la page.

Source : Meteo-France, « Donnees climatologiques de base - quotidiennes »,
data.gouv.fr, Licence Ouverte 2.0. Un fichier par departement, un seul pour la
Corse (« 20 »), republie chaque matin vers 6 h UTC. La valeur RR du jour J est
la pluie tombee de 06 h UTC le jour J a 06 h UTC le jour J+1 : les dates sont
reprises telles quelles, sans conversion.

Ce que fait le script :
  - il trouve l'adresse des fichiers du moment par l'API de data.gouv.fr, et
    non par une adresse en dur : leur nom porte les annees (« latest-2025-2026 »)
    et changera en janvier ;
  - il releve la date de publication de chaque fichier (en-tete Last-Modified) ;
  - il ne garde que les 96 stations, sur les 400 derniers jours ;
  - un jour sans valeur est ecrit null, JAMAIS 0 : un jour sans donnee est une
    erreur, pas un jour sec ;
  - il compte les jours de silence de chaque station, jusqu'au dernier jour de
    pluie publie dans le fichier de son departement, et signale celles qui se
    taisent depuis 3 jours ou plus ;
  - un fichier publie avant aujourd'hui est « en_retard » ; un fichier
    illisible ou introuvable est « absent » : ses jours restent null, ou sont
    repris tels quels du pluie.json precedent s'il est fourni. Rien n'est
    invente ;
  - il ecrit la source, la licence et la mention a citer.

Aucune ecriture ailleurs que dans le fichier de sortie.

Usage :
    python extraction_meteofrance.py [--sortie pluie.json] [--precedent pluie.json]

    Hors ligne, sur des fichiers deja telecharges (reference, tests) :
    python extraction_meteofrance.py --dossier DIR --publications F.json
                                     --date AAAA-MM-JJ --sortie pluie-reference.json
"""
import argparse, datetime as dt, email.utils, gzip, io, json, os, re, sys, time, urllib.request

sys.stdout.reconfigure(encoding="utf-8")

RACINE = os.path.dirname(os.path.abspath(__file__))

JEU = "6569b51ae64326786e4e8e1a"
API_JEU = "https://www.data.gouv.fr/api/1/datasets/%s/" % JEU
SOURCE = {
    "producteur": "Météo-France",
    "jeu": "Données climatologiques de base - quotidiennes",
    "url": "https://www.data.gouv.fr/datasets/donnees-climatologiques-de-base-quotidiennes",
    "licence": "Licence Ouverte 2.0",
    # L'ancienne adresse etalab.gouv.fr renvoie desormais vers l'accueil de
    # data.gouv.fr (constate le 06/10/2026) : on pointe la page de la licence.
    "licence_url": "https://www.data.gouv.fr/pages/legal/licences/etalab-2.0",
}
JOURNEE = "de 06 h UTC le jour J à 06 h UTC le jour J+1"
# Decision de Nicolas du 06/10/2026 : la licence impose la source ET la date de
# mise a jour. La date est celle du fichier Meteo-France qui a servi.
MENTION = "Données pluviométriques : Météo-France, mise à jour du %s"
TITRE = re.compile(r"^QUOT_departement_(\d{2,3})_periode_(\d{4})-(\d{4})_RR-T-Vent$")
JOUR_MF = re.compile(r"^\d{8}$")
DUREE_J = 400                 # 12 mois de simulation, la fenetre de la serie B, et de la marge
SEUIL_SILENCE_J = 3           # decision du 06/10/2026 : alerte au 3e jour de silence
ESSAIS = 3
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


class Echec(Exception):
    """Rien d'utilisable : aucun fichier lu, ou adresse des fichiers introuvable."""


# ------------------------------------------------------------------ dates
def instant_utc(entete_http):
    """En-tete Last-Modified -> 'AAAA-MM-JJTHH:MM:SSZ'."""
    t = email.utils.parsedate_to_datetime(entete_http).astimezone(dt.timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def date_paris(iso_utc):
    """Date a Paris d'un instant UTC. Heure d'ete du dernier dimanche de mars
    au dernier dimanche d'octobre, a 01 h UTC (regle europeenne)."""
    t = dt.datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ")

    def dernier_dimanche(annee, mois):
        d = dt.date(annee, mois, 31)
        return d - dt.timedelta(days=(d.weekday() + 1) % 7)

    ete = (dt.datetime.combine(dernier_dimanche(t.year, 3), dt.time(1)) <= t
           < dt.datetime.combine(dernier_dimanche(t.year, 10), dt.time(1)))
    return (t + dt.timedelta(hours=2 if ete else 1)).date()


def date_longue(d):
    """6 octobre 2026, 1er octobre 2026."""
    return "%s %s %d" % ("1er" if d.day == 1 else d.day, MOIS[d.month - 1], d.year)


def mention(d):
    return MENTION % date_longue(d)


# ------------------------------------------------------------------ reseau
def lire_url(url, binaire=False, delai=120):
    for essai in range(ESSAIS):
        try:
            with urllib.request.urlopen(url, timeout=delai) as r:
                corps = r.read()
                return (corps, r.headers.get("Last-Modified")) if binaire else json.loads(corps)
        except Exception:
            if essai == ESSAIS - 1:
                raise
            time.sleep(5 * (essai + 1))


def resoudre(departements):
    """Adresse du fichier le plus recent de chaque departement, par l'API de
    data.gouv.fr. Le plus recent = la periode qui finit le plus tard."""
    choix = {}
    for r in lire_url(API_JEU, delai=60).get("resources") or []:
        m = TITRE.match(r.get("title") or "")
        if not m or m.group(1) not in departements:
            continue
        cle = (int(m.group(3)), int(m.group(2)))
        if m.group(1) not in choix or cle > choix[m.group(1)][0]:
            choix[m.group(1)] = (cle, r["url"])
    return {dd: url for dd, (_, url) in choix.items()}


# ------------------------------------------------------------------ lecture
def lire_fichier(contenu_gz, voulus, borne):
    """Valeurs RR des stations voulues depuis la borne, et dernier jour de pluie
    publie dans le fichier, toutes stations confondues.

    Ce dernier jour est celui qui porte une valeur RR, pas la derniere ligne :
    le 06/10/2026, deux fichiers (05, 31) avaient deja des lignes du 05/10, avec
    la seule temperature minimale de la nuit. La pluie du 05/10 n'etait publiee
    nulle part ; la compter aurait mis 93 departements « sans donnee » a tort."""
    lignes = gzip.decompress(contenu_gz).decode("utf-8").splitlines()
    col = {c.strip(): k for k, c in enumerate(lignes[0].split(";"))}
    for nom in ("NUM_POSTE", "AAAAMMJJ", "RR"):
        if nom not in col:
            raise ValueError("colonne %s absente" % nom)
    valeurs = {n: {} for n in voulus}
    fin = None
    for l in lignes[1:]:
        c = l.split(";")
        if len(c) <= max(col["NUM_POSTE"], col["AAAAMMJJ"], col["RR"]):
            continue
        j = c[col["AAAAMMJJ"]].strip()
        if not JOUR_MF.match(j):
            continue
        v = c[col["RR"]].strip()
        if v == "":                          # vide = pas de donnee, jamais 0
            continue
        iso = "%s-%s-%s" % (j[:4], j[4:6], j[6:])
        if fin is None or iso > fin:
            fin = iso
        n = c[col["NUM_POSTE"]].strip()
        if n in valeurs and iso >= borne:
            valeurs[n][iso] = float(v)
    return valeurs, fin


def jours(debut, fin):
    d0, d1 = dt.date.fromisoformat(debut), dt.date.fromisoformat(fin)
    return [(d0 + dt.timedelta(days=k)).isoformat() for k in range((d1 - d0).days + 1)]


def construire(stations, fichiers, aujourd_hui, precedent=None):
    """stations   : la liste figee (code, num)
    fichiers      : {dd: {"contenu": octets ou None, "publie_le": iso ou None,
                          "fichier": adresse}}
    aujourd_hui   : date de Paris du tour
    precedent     : pluie.json du tour precedent, pour les fichiers absents
    """
    par_fichier = {}
    for s in stations:
        par_fichier.setdefault(s["num"][:2], set()).add(s["num"])
    borne = (aujourd_hui - dt.timedelta(days=DUREE_J + 60)).isoformat()

    lus, fins = {}, {}
    for dd, voulus in sorted(par_fichier.items()):
        f = fichiers.get(dd) or {}
        if f.get("contenu") is None:
            continue
        try:
            lus[dd], fins[dd] = lire_fichier(f["contenu"], voulus, borne)
        except Exception as e:
            print("ATTENTION | fichier %s illisible, traite comme absent : %s" % (dd, e))
            continue
        if fins[dd] is None:
            del lus[dd], fins[dd]
    if not lus:
        raise Echec("aucun fichier Meteo-France n'a pu etre lu")

    fin = max(fins.values())
    debut = (dt.date.fromisoformat(fin) - dt.timedelta(days=DUREE_J - 1)).isoformat()
    dates = jours(debut, fin)
    prec = (precedent or {}).get("stations") or {}

    sortie = {}
    for s in stations:
        dd, n = s["num"][:2], s["num"]
        f = fichiers.get(dd) or {}
        if dd in lus:
            vals, fin_f, pub = lus[dd][n], fins[dd], f.get("publie_le")
            etat = "a_jour" if pub and date_paris(pub) >= aujourd_hui else "en_retard"
        else:
            # Fichier absent ou illisible : on ne fabrique rien. Les valeurs deja
            # publiees sont reprises telles quelles si la station n'a pas change.
            vals, fin_f, pub = {}, None, None
            p = prec.get(s["code"])
            if p and p.get("num") == n:
                vals = {d: v for d, v in zip(jours(precedent["debut"], precedent["fin"]), p.get("rr") or [])
                        if v is not None}
                fin_f, pub = p.get("fin_fichier"), p.get("publie_le")
            etat = "absent"
        rr = [vals.get(d) for d in dates]
        connus = [d for d, v in zip(dates, rr) if v is not None]
        dernier = connus[-1] if connus else None
        if fin_f and dernier:
            silence = (dt.date.fromisoformat(fin_f) - dt.date.fromisoformat(dernier)).days
        elif fin_f:
            silence = len(jours(debut, fin_f))
        else:
            silence = None
        sortie[s["code"]] = {"num": n, "etat": etat, "publie_le": pub, "fichier": f.get("fichier"),
                             "fin_fichier": fin_f, "dernier_jour": dernier, "silence_j": silence,
                             "rr": rr}

    pubs = [date_paris(fichiers[dd]["publie_le"]) for dd in lus if fichiers[dd].get("publie_le")]
    if not pubs:
        raise Echec("aucune date de publication connue")
    return {"version": 1, "mention": mention(max(pubs)), "source": SOURCE, "journee": JOURNEE,
            "debut": debut, "fin": fin, "stations": sortie}


# ------------------------------------------------------------------ ecriture
def nombre(v):
    return None if v is None else (int(v) if v == int(v) else v)


def ecrire(doc, chemin):
    """Une station par ligne : le fichier reste lisible et ses differences aussi."""
    tete = [" %s: %s," % (json.dumps(k), json.dumps(v, ensure_ascii=False))
            for k, v in doc.items() if k != "stations"]
    corps = ",\n".join("  %s: %s" % (json.dumps(code), json.dumps(
        dict(s, rr=[nombre(v) for v in s["rr"]]), ensure_ascii=False, separators=(",", ":")))
        for code, s in doc["stations"].items())
    texte = "{\n" + "\n".join(tete) + '\n "stations": {\n' + corps + "\n }\n}\n"
    json.loads(texte)
    io.open(chemin, "w", encoding="utf-8", newline="\n").write(texte)


def rapport(doc, stations):
    noms = {s["code"]: s.get("nom", "") for s in stations}
    st = doc["stations"]
    etats = {e: sorted(c for c, s in st.items() if s["etat"] == e) for e in ("a_jour", "en_retard", "absent")}
    print("pluie.json : %d stations, du %s au %s (%d jours)"
          % (len(st), doc["debut"], doc["fin"], len(jours(doc["debut"], doc["fin"]))))
    print("Mention : %s" % doc["mention"])
    print("Fichiers a jour : %d, en retard : %d, absents : %d"
          % tuple(len(etats[e]) for e in ("a_jour", "en_retard", "absent")))
    for e in ("en_retard", "absent"):
        for c in etats[e]:
            print("ATTENTION | %s : fichier %s (publie le %s)" % (c, e.replace("_", " "), st[c]["publie_le"]))
    for c, s in st.items():
        if s["silence_j"] is not None and s["silence_j"] >= SEUIL_SILENCE_J:
            print("ALERTE    | station silencieuse : %s %s (%s), %d jours sans donnee, derniere valeur le %s"
                  % (c, noms.get(c, ""), s["num"], s["silence_j"], s["dernier_jour"]))


# ------------------------------------------------------------------ main
def trouver(dossier, dd):
    for nom in sorted(os.listdir(dossier)):
        if nom.endswith(".csv.gz") and (nom == "Q_%s.csv.gz" % dd or nom.startswith("Q_%s_" % dd)):
            return os.path.join(dossier, nom)
    return None


def main():
    ap = argparse.ArgumentParser(description="Extraction Meteo-France -> pluie.json")
    ap.add_argument("--stations", default=os.path.join(RACINE, "stations.json"))
    ap.add_argument("--sortie", default=os.path.join(RACINE, "pluie.json"))
    ap.add_argument("--precedent", help="pluie.json du tour precedent, pour les fichiers absents")
    ap.add_argument("--dossier", help="hors ligne : fichiers deja telecharges")
    ap.add_argument("--publications", help="hors ligne : dates de publication, par departement")
    ap.add_argument("--date", help="hors ligne : date du tour, AAAA-MM-JJ")
    a = ap.parse_args()

    stations = json.load(io.open(a.stations, encoding="utf-8"))["stations"]
    departements = {s["num"][:2] for s in stations}
    precedent = None
    if a.precedent and os.path.exists(a.precedent):
        precedent = json.load(io.open(a.precedent, encoding="utf-8"))

    fichiers = {}
    try:
        if a.dossier:
            if not (a.publications and a.date):
                raise Echec("hors ligne, --publications et --date sont obligatoires")
            pubs = json.load(io.open(a.publications, encoding="utf-8"))
            aujourd_hui = dt.date.fromisoformat(a.date)
            for dd in sorted(departements):
                chemin = trouver(a.dossier, dd)
                p = pubs.get(dd) or {}
                fichiers[dd] = {"contenu": io.open(chemin, "rb").read() if chemin else None,
                                "publie_le": p.get("publie_le"), "fichier": p.get("fichier")}
        else:
            aujourd_hui = date_paris(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            try:
                urls = resoudre(departements)
            except Exception as e:
                # data.gouv.fr injoignable : on retente les adresses du tour precedent.
                urls = {s["num"][:2]: s["fichier"] for s in ((precedent or {}).get("stations") or {}).values()
                        if s.get("fichier")}
                print("ATTENTION | API data.gouv.fr injoignable (%s) : %d adresse(s) reprises du tour precedent"
                      % (e, len(urls)))
                if not urls:
                    raise Echec("adresse des fichiers introuvable")
            for dd in sorted(departements):
                if dd not in urls:
                    print("ATTENTION | aucun fichier publie pour le departement %s" % dd)
                    fichiers[dd] = {"contenu": None, "publie_le": None, "fichier": None}
                    continue
                try:
                    corps, lm = lire_url(urls[dd], binaire=True)
                    fichiers[dd] = {"contenu": corps, "publie_le": instant_utc(lm), "fichier": urls[dd]}
                except Exception as e:
                    print("ATTENTION | fichier %s non telecharge : %s" % (dd, e))
                    fichiers[dd] = {"contenu": None, "publie_le": None, "fichier": urls[dd]}
        doc = construire(stations, fichiers, aujourd_hui, precedent)
    except Echec as e:
        print("ECHEC | %s. pluie.json n'est pas reecrit." % e)
        return 1

    ecrire(doc, a.sortie)
    rapport(doc, stations)
    return 0


if __name__ == "__main__":
    sys.exit(main())
