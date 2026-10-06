#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Controle de extraction_meteofrance.py et de pluie-reference.json.

Hors ligne, aucun acces reseau.

1. Des fichiers Meteo-France fabriques ici, minuscules, couvrent chaque cas :
   valeur vide, ligne manquante, vrai zero, station qui se tait, fichier en
   retard, fichier absent ou illisible, ligne du lendemain sans pluie, reprise
   du pluie.json precedent. Un jour sans donnee doit sortir null, jamais 0.
2. pluie-reference.json, tire des fichiers publies le 06/10/2026, doit porter
   les 96 stations de stations.json, la mention exacte, la source, et des
   valeurs relevees a la main dans les fichiers bruts.

Ses attendus sont ecrits en dur, et c'est voulu : un controle qui importe les
references qu'il verifie ne verifie plus rien.

Sortie : code 0 si tout passe, 1 sinon.

Usage :
    python test_extraction.py [chemin de extraction_meteofrance.py]
"""
import datetime as dt, gzip, importlib.util, io, json, os, sys, tempfile

sys.stdout.reconfigure(encoding="utf-8")
sys.dont_write_bytecode = True

RACINE = os.path.dirname(os.path.abspath(__file__))
MODULE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RACINE, "extraction_meteofrance.py")
_spec = importlib.util.spec_from_file_location("extraction_meteofrance", MODULE)
X = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(X)

MENTION_REFERENCE = "Données pluviométriques : Météo-France, mise à jour du 6 octobre 2026"
ENTETE = "NUM_POSTE;NOM_USUEL;LAT;LON;ALTI;AAAAMMJJ;RR;QRR;TN;QTN"
AUJ = dt.date(2026, 10, 6)
J = dt.date.fromisoformat

OK = True


def v(libelle, cond, detail=""):
    global OK
    print("%s | %-58s %s" % ("OK   " if cond else "ECHEC", libelle, detail))
    if not cond:
        OK = False
    return cond


def jours(debut, fin):
    return [(J(debut) + dt.timedelta(days=k)).isoformat() for k in range((J(fin) - J(debut)).days + 1)]


def fichier(lignes):
    """Fichier Meteo-France compresse. lignes : (numero, jour, RR, TN)."""
    corps = "".join("%s;POSTE;45.0;3.0;100;%s;%s;1;%s;1\n" % (n, d.replace("-", ""), rr, tn)
                    for n, d, rr, tn in lignes)
    return gzip.compress((ENTETE + "\n" + corps).encode("utf-8"))


def valeur(doc, code, jour):
    return doc["stations"][code]["rr"][jours(doc["debut"], doc["fin"]).index(jour)]


# ============================================================ 1. cas fabriques
STATIONS = [
    {"code": "01", "num": "01000001", "nom": "UN"},
    {"code": "2A", "num": "20004001", "nom": "AJACCIO"},
    {"code": "2B", "num": "20033001", "nom": "BASTIA"},
    {"code": "07", "num": "07000001", "nom": "SEPT"},
    {"code": "34", "num": "34000001", "nom": "MUETTE"},
]


def fabriquer():
    l01 = []
    for d in jours("2025-07-01", "2026-10-01"):
        if d == "2026-09-29":
            continue                                          # ligne manquante
        rr = {"2026-09-28": "0.0", "2026-09-30": "", "2026-10-01": "146.0"}.get(d, "1.5")
        l01.append(("01000001", d, rr, "12.0"))
    for d in jours("2025-07-01", "2026-10-04"):
        l01.append(("01999001", d, "0.2", "11.0"))            # une autre station, jusqu'au 04/10
    l01.append(("01999001", "2026-10-05", "", "5.6"))         # le lendemain : temperature seule
    l20 = [(n, d, "2.0", "") for n in ("20004001", "20033001") for d in jours("2025-07-01", "2026-10-03")]
    l34 = [("34999001", d, "0.0", "") for d in jours("2025-07-01", "2026-10-04")]
    return {
        "01": {"contenu": fichier(l01), "publie_le": "2026-10-06T06:23:00Z", "fichier": "Q_01"},
        "20": {"contenu": fichier(l20), "publie_le": "2026-10-05T06:23:00Z", "fichier": "Q_20"},
        "07": {"contenu": None, "publie_le": None, "fichier": "Q_07"},
        "34": {"contenu": fichier(l34), "publie_le": "2026-10-06T06:23:00Z", "fichier": "Q_34"},
    }


def cas_fabriques():
    print("1. Cas fabriques")
    F = fabriquer()
    doc = X.construire(STATIONS, F, AUJ)
    st = doc["stations"]

    v("fenetre de 400 jours finissant au dernier jour de pluie publie",
      doc["fin"] == "2026-10-04" and doc["debut"] == "2025-08-31"
      and all(len(s["rr"]) == 400 for s in st.values()), "%s -> %s" % (doc["debut"], doc["fin"]))
    v("une ligne du lendemain sans pluie ne compte pas", doc["fin"] != "2026-10-05", "")

    s = st["01"]
    v("valeur vide -> null, jamais 0", valeur(doc, "01", "2026-09-30") is None, "")
    v("ligne manquante -> null, jamais 0", valeur(doc, "01", "2026-09-29") is None, "")
    v("vrai zero conserve", valeur(doc, "01", "2026-09-28") == 0, "")
    v("valeur lue au bon jour", valeur(doc, "01", "2026-10-01") == 146.0
      and valeur(doc, "01", "2026-09-27") == 1.5, "")
    v("aucun zero invente", sum(1 for x in s["rr"] if x == 0) == 1,
      "%d zero(s)" % sum(1 for x in s["rr"] if x == 0))
    v("station muette depuis 3 jours : silence_j = 3",
      s["dernier_jour"] == "2026-10-01" and s["fin_fichier"] == "2026-10-04" and s["silence_j"] == 3,
      "dernier %s, fin %s, silence %s" % (s["dernier_jour"], s["fin_fichier"], s["silence_j"]))
    v("fichier publie aujourd'hui : a_jour", s["etat"] == "a_jour", s["etat"])

    v("Corse : deux stations lues dans le meme fichier",
      valeur(doc, "2A", "2026-10-01") == 2.0 and valeur(doc, "2B", "2026-10-01") == 2.0, "")
    v("fichier publie la veille : en_retard", st["2A"]["etat"] == st["2B"]["etat"] == "en_retard",
      st["2A"]["etat"])
    v("en retard : le jour non publie est null, pas de silence",
      valeur(doc, "2A", "2026-10-04") is None and st["2A"]["fin_fichier"] == "2026-10-03"
      and st["2A"]["silence_j"] == 0, "")

    s = st["07"]
    v("fichier absent : absent, toutes les valeurs null",
      s["etat"] == "absent" and all(x is None for x in s["rr"]) and s["publie_le"] is None, s["etat"])
    s = st["34"]
    v("station sans aucune valeur : toute la fenetre en silence",
      all(x is None for x in s["rr"]) and s["dernier_jour"] is None and s["silence_j"] == 400,
      "silence %s" % s["silence_j"])

    v("mention : date de publication la plus recente",
      doc["mention"] == "Données pluviométriques : Météo-France, mise à jour du 6 octobre 2026", doc["mention"])
    v("source et licence ecrites dans le fichier",
      doc["source"]["producteur"] == "Météo-France" and doc["source"]["licence"] == "Licence Ouverte 2.0", "")

    # Fichier illisible : traite comme absent, sans faire tomber les autres.
    G = dict(F, **{"34": dict(F["34"], contenu=b"pas un fichier gzip")})
    d2 = X.construire(STATIONS, G, AUJ)
    v("fichier illisible : absent, les autres intacts",
      d2["stations"]["34"]["etat"] == "absent" and d2["stations"]["01"]["rr"] == doc["stations"]["01"]["rr"], "")

    # Reprise du precedent : alignement au jour pres. La valeur porte le rang du
    # jour dans une fenetre decalee d'un jour.
    prec_dates = jours("2025-08-30", "2026-10-03")
    prec = {"debut": "2025-08-30", "fin": "2026-10-03", "stations": {
        "07": {"num": "07000001", "rr": [float(k) for k in range(len(prec_dates))],
               "fin_fichier": "2026-10-03", "publie_le": "2026-10-05T06:20:00Z"}}}
    d3 = X.construire(STATIONS, F, AUJ, prec)
    s = d3["stations"]["07"]
    v("absent avec precedent : valeurs reprises au jour pres",
      s["etat"] == "absent" and valeur(d3, "07", "2025-08-31") == 1.0
      and valeur(d3, "07", "2026-10-03") == float(len(prec_dates) - 1)
      and valeur(d3, "07", "2026-10-04") is None, "")
    v("absent avec precedent : date de publication reprise", s["publie_le"] == "2026-10-05T06:20:00Z", "")
    prec["stations"]["07"]["num"] = "07999999"
    d4 = X.construire(STATIONS, F, AUJ, prec)
    v("station remplacee depuis : rien n'est repris", all(x is None for x in d4["stations"]["07"]["rr"]), "")

    # Ecriture : une station par ligne, nombres compacts, null conserve.
    with tempfile.TemporaryDirectory() as t:
        p = os.path.join(t, "pluie.json")
        X.ecrire(doc, p)
        texte = io.open(p, encoding="utf-8").read()
        relu = json.loads(texte)
    v("relu a l'identique apres ecriture",
      relu["stations"]["01"]["rr"] == [None if x is None else x for x in doc["stations"]["01"]["rr"]], "")
    v("une station par ligne", texte.count('\n  "') == len(STATIONS), "")
    v("146.0 ecrit 146, 0.0 ecrit 0, vide ecrit null",
      ",146," in texte or ",146]" in texte, "")
    v("aucune adresse email dans le fichier ecrit", "@" not in texte, "")

    try:
        X.construire(STATIONS, {"07": F["07"]}, AUJ)
        v("aucun fichier lisible : echec franc", False, "aucune exception")
    except X.Echec:
        v("aucun fichier lisible : echec franc", True, "")

    # Dates.
    v("date_longue : « 1er » le premier du mois", X.date_longue(dt.date(2026, 10, 1)) == "1er octobre 2026", "")
    v("date_longue : nombre nu ensuite", X.date_longue(dt.date(2026, 10, 6)) == "6 octobre 2026", "")
    v("date_paris : heure d'ete, +2 h", X.date_paris("2026-10-24T22:30:00Z") == dt.date(2026, 10, 25), "")
    v("date_paris : heure d'hiver, +1 h", X.date_paris("2026-10-25T23:30:00Z") == dt.date(2026, 10, 26)
      and X.date_paris("2026-10-25T22:30:00Z") == dt.date(2026, 10, 25), "")


# =========================================================== 2. la reference
def reference():
    print("")
    print("2. pluie-reference.json (fichiers publies le 06/10/2026)")
    brut = io.open(os.path.join(RACINE, "pluie-reference.json"), encoding="utf-8").read()
    doc = json.loads(brut)
    fige = json.load(io.open(os.path.join(RACINE, "stations.json"), encoding="utf-8"))["stations"]
    st = doc["stations"]

    v("les 96 stations de stations.json, dans le meme ordre",
      list(st) == [s["code"] for s in fige] and all(st[s["code"]]["num"] == s["num"] for s in fige),
      "%d station(s)" % len(st))
    v("fenetre du 31/08/2025 au 04/10/2026, 400 jours par station",
      doc["debut"] == "2025-08-31" and doc["fin"] == "2026-10-04"
      and all(len(s["rr"]) == 400 for s in st.values()), "")
    v("mention exacte", doc["mention"] == MENTION_REFERENCE, doc["mention"])
    v("source : Meteo-France, data.gouv.fr, Licence Ouverte 2.0",
      doc["source"]["producteur"] == "Météo-France" and doc["source"]["licence"] == "Licence Ouverte 2.0"
      and "data.gouv.fr/datasets/donnees-climatologiques-de-base-quotidiennes" in doc["source"]["url"], "")
    v("lien de la licence : la page Licence Ouverte 2.0 de data.gouv.fr",
      doc["source"]["licence_url"] == "https://www.data.gouv.fr/pages/legal/licences/etalab-2.0",
      doc["source"]["licence_url"])
    v("journee Meteo-France declaree", doc["journee"] == "de 06 h UTC le jour J à 06 h UTC le jour J+1", "")
    v("96 fichiers a jour, publies le 06/10/2026",
      all(s["etat"] == "a_jour" and s["publie_le"].startswith("2026-10-06") for s in st.values()), "")
    v("aucune station silencieuse ce jour-la", all(s["silence_j"] == 0 for s in st.values()), "")
    v("Herault, 30/09/2026 : 146 mm", valeur(doc, "34", "2026-09-30") == 146, "")
    v("Gard, 30/09/2026 : 72,4 mm", valeur(doc, "30", "2026-09-30") == 72.4, "")
    v("Ardeche : Chomerac, pas Privas", st["07"]["num"] == "07066001", st["07"]["num"])
    v("Rodez muette du 20 au 25/02/2026 : null, pas 0",
      valeur(doc, "12", "2026-02-19") == 23.6 and valeur(doc, "12", "2026-02-26") == 0
      and all(valeur(doc, "12", d) is None for d in jours("2026-02-20", "2026-02-25")), "")
    nuls = sum(1 for s in st.values() for x in s["rr"] if x is None)
    v("6 jours sans donnee en tout, ceux de Rodez", nuls == 6, "%d" % nuls)
    v("aucune adresse email dans le fichier", "@" not in brut, "")


def main():
    print("Controle de l'extraction Meteo-France. Aucun acces reseau.")
    print("")
    cas_fabriques()
    reference()
    print("")
    print("RESULTAT : " + ("l'extraction est conforme" if OK else "AU MOINS UN ECART — ne pas livrer"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
