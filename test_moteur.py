#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Controle de moteur.py sur les observations Meteo-France.

Hors ligne, aucun acces reseau. Rien n'est ecrit dans le depot : maj_etat.py
et le moteur tournent sur des copies, dans un dossier temporaire.

1. La redaction : arrondi au millimetre, la demie vers le haut ; « 1er » ;
   mention de source datee a Paris ; une seule phrase de serie A, sans
   « orage », « averses », « grele » ni « jusqu'a ».
2. La detection : un jour sans donnee ne declenche rien et ne compte pas comme
   jour de pluie.
3. Le jour cite : le plus fort des jours consecutifs a 30 mm, connu au mail 1
   (J+5), sans remonter dans le verrou precedent.
4. Sur pluie-reference.json, la simulation retrouve les 236 sequences de
   sequences-reference.json, une par une : 472 campagnes.
5. Le moteur tel que le workflow le lance, sur la reference au 06/10/2026 :
   les phrases de l'Herault et du Gard, la mention, aucune erreur.
6. Les jours sans donnee : departement en erreur, jamais un jour sec ; au-dela
   de 20 departements, maj_etat.py refuse de publier.
7. verif_etat.py controle etat.json, pluie.json et stations.json.

Ses attendus sont ecrits en dur, et c'est voulu.

Sortie : code 0 si tout passe, 1 sinon.

Usage :
    python test_moteur.py [chemin de moteur.py]
"""
import copy, datetime as dt, importlib.util, io, json, os, shutil, subprocess, sys, tempfile

sys.stdout.reconfigure(encoding="utf-8")
sys.dont_write_bytecode = True

RACINE = os.path.dirname(os.path.abspath(__file__))
MOTEUR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RACINE, "moteur.py")
for _k in ("VP_ETAT", "VP_EXIGE_ETAT", "VP_PIC", "VP_SEUIL_JOUR", "VP_NB_JOURS",
           "VP_DATE", "VP_PLUIE", "VP_PROFONDEUR", "VP_EXPIRATION"):
    os.environ.pop(_k, None)
os.environ["VP_DEPTS"] = os.path.join(RACINE, "depts.json")


def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M = charger("moteur", MOTEUR)
X = charger("extraction_meteofrance", os.path.join(RACINE, "extraction_meteofrance.py"))

EN = {x["code"]: x["DEPT_EN"] for x in json.load(io.open(
    os.path.join(RACINE, "libelles-departements.json"), encoding="utf-8"))}
PHRASE_HERAULT = "Le 30 septembre, 146 mm de pluie sont tombés en 24 heures dans l'Hérault."
PHRASE_GARD = "Le 30 septembre, 72 mm de pluie sont tombés en 24 heures dans le Gard."
MENTION_0610 = "Données pluviométriques : Météo-France, mise à jour du 6 octobre 2026"
MOTS_INTERDITS = ("orage", "averse", "grêle", "jusqu'à")

OK = True


def v(libelle, cond, detail=""):
    global OK
    print("%s | %-58s %s" % ("OK   " if cond else "ECHEC", libelle, detail))
    if not cond:
        OK = False
    return cond


def dates_depuis(debut, n):
    d0 = dt.date.fromisoformat(debut)
    return [(d0 + dt.timedelta(days=k)).isoformat() for k in range(n)]


# ================================================================ 1. redaction
def redaction():
    print("1. Redaction")
    for val, attendu in ((146.0, "146"), (72.4, "72"), (212.5, "213"), (0.5, "1"),
                         (30.0, "30"), (29.4, "29"), (99.5, "100")):
        v("arrondi : %s -> %s mm" % (val, attendu), M._mm(val) == attendu, "obtenu %s" % M._mm(val))
    v("« 1er » le premier du mois", M.jour_long("2026-10-01") == "1er octobre", M.jour_long("2026-10-01"))
    v("nombre nu ensuite, jamais « 2er » ni « 31er »",
      all(not M.jour_long("2026-03-%02d" % j).startswith("%der" % j) for j in range(2, 32)), "")
    v("mention du 06/10/2026", M.mention("2026-10-06T06:23:06Z") == MENTION_0610, M.mention("2026-10-06T06:23:06Z"))
    v("mention du 1er du mois",
      M.mention("2026-10-01T06:00:00Z") == "Données pluviométriques : Météo-France, mise à jour du 1er octobre 2026", "")
    v("mention sans date connue : aucune", M.mention(None) is None, "")
    instants = ["2026-03-29T00:59:59Z", "2026-03-29T01:00:00Z", "2026-06-30T22:30:00Z", "2026-10-24T22:30:00Z",
                "2026-10-25T00:59:59Z", "2026-10-25T01:00:00Z", "2026-10-25T23:30:00Z", "2026-12-31T23:30:00Z"]
    v("date de Paris identique a celle de l'extraction, aux changements d'heure",
      all(M.date_paris(t) == X.date_paris(t) for t in instants), "")
    v("mention datee a Paris : 22 h 30 UTC le 30/06 = 1er juillet",
      M.mention("2026-06-30T22:30:00Z").endswith("1er juillet 2026"), "")

    a = M.bloc_meteo({"serie": "A", "cite_date": "2026-09-30", "cite_mm": 146.0}, "dans l'Hérault")
    v("phrase de serie A", a == PHRASE_HERAULT, a)
    b = M.bloc_meteo({"serie": "B", "debut_fenetre": "2026-02-06", "episode": "2026-03-07", "jours_pluie": 15},
                     "dans le Finistère")
    v("phrase de serie B inchangee",
      b == "Entre le 6 février et le 7 mars, 15 jours de pluie ont été relevés dans le Finistère.", b)
    phrases = [M.bloc_meteo({"serie": "A", "cite_date": "2026-%02d-%02d" % (m, j), "cite_mm": mm}, EN[c])
               for c in EN for m, j, mm in ((1, 1, 30.0), (8, 20, 38.8), (12, 31, 212.5))]
    v("aucune phrase de serie A avec orage, averses, grele, jusqu'a",
      not [p for p in phrases if any(w in p.lower() for w in MOTS_INTERDITS)], "%d phrases" % len(phrases))
    v("aucune decimale dans les millimetres",
      not [p for p in phrases if not p.split(" mm de pluie")[0].split()[-1].isdigit()], "")


# ================================================================ 2. detection
def detection():
    print("")
    print("2. Detection, jours sans donnee")
    d = dates_depuis("2026-01-01", 3)
    v("serie A : 35 mm declenche, un jour vide jamais",
      [(i, s) for i, s, _ in M.declencheurs([None, 35.0, 10.0], d)] == [(1, "A")], "")
    v("que des jours vides : rien", M.declencheurs([None] * 40, dates_depuis("2026-01-01", 40)) == [], "")
    d = dates_depuis("2026-01-01", 30)
    p = [2.0] * 14 + [0.0] * 15 + [None]
    v("serie B : 14 jours de pluie et un jour vide ne font pas 15", M.declencheurs(p, d) == [], "")
    p[-1] = 1.0
    v("serie B : le 15e jour de pluie declenche, le jour meme",
      [(i, s) for i, s, _ in M.declencheurs(p, d)] == [(29, "B")], "")
    p = [2.0] * 15 + [0.0] * 14 + [None]
    trig = [i for i, s, _ in M.declencheurs(p, d) if s == "B"]
    v("serie B : un jour vide ne declenche pas, meme fenetre pleine", 29 not in trig and 14 in trig, "")


# ================================================================ 3. jour cite
def jour_cite():
    print("")
    print("3. Jour cite")
    d = dates_depuis("2026-09-28", 10)
    v("le plus fort des jours consecutifs", M.jour_cite([40.0, 80.0, 50.0, 0.0], d, 0) == (d[1], 80.0), "")
    p = [30.0 + k for k in range(8)]
    v("connu au mail 1 : jusqu'a J+5, pas au-dela", M.jour_cite(p, d, 0) == (d[5], 35.0),
      "%s" % (M.jour_cite(p, d, 0),))
    v("un jour sans donnee interrompt l'episode", M.jour_cite([40.0, None, 90.0], d, 0) == (d[0], 40.0), "")
    v("sans remonter dans le verrou precedent",
      M.jour_cite([90.0, 40.0], d, 1, dt.date.fromisoformat(d[1])) == (d[1], 40.0), "")
    v("hors verrou, l'episode commence plus tot", M.jour_cite([90.0, 40.0], d, 1, None) == (d[0], 90.0), "")
    v("a egalite, le jour le plus tot", M.jour_cite([50.0, 50.0], d, 0) == (d[0], 50.0), "")


# ============================================================ 4. reference
def reference():
    print("")
    print("4. Simulation sur pluie-reference.json")
    doc = json.load(io.open(os.path.join(RACINE, "pluie-reference.json"), encoding="utf-8"))
    attendu = json.load(io.open(os.path.join(RACINE, "sequences-reference.json"), encoding="utf-8"))
    dates = dates_depuis(doc["debut"], len(next(iter(doc["stations"].values()))["rr"]))
    i0, i1 = dates.index(attendu["periode"][0]), dates.index(attendu["periode"][1])
    obtenu, ecarts = {}, []
    for code, s in doc["stations"].items():
        seqs = []
        for x in M.simuler(s["rr"], dates, i0, i1):
            if x["serie"] == "A":
                seqs.append({"episode": x["episode"], "serie": "A", "cite_date": x["cite_date"],
                             "cite_mm": x["cite_mm"]})
            else:
                seqs.append({"episode": x["episode"], "serie": "B", "jours_pluie": x["jours_pluie"],
                             "debut_fenetre": x["debut_fenetre"]})
        obtenu[code] = seqs
        if seqs != attendu["par_departement"][code]:
            ecarts.append(code)
    total = sum(len(x) for x in obtenu.values())
    v("236 sequences, 472 campagnes", total == 236 and attendu["campagnes"] == 472,
      "%d sequences, %d campagnes" % (total, 2 * total))
    v("les 96 departements identiques au rejeu, sequence par sequence", not ecarts, ", ".join(ecarts[:8]))
    h = [x for x in obtenu["34"] if x["episode"] == "2026-09-30"]
    g = [x for x in obtenu["30"] if x["episode"] == "2026-09-30"]
    v("Herault : sequence de serie A le 30/09", len(h) == 1 and h[0]["serie"] == "A", "")
    v("Gard : sequence de serie A le 30/09", len(g) == 1 and g[0]["serie"] == "A", "")
    v("phrase de l'Herault", h and M.bloc_meteo(h[0], EN["34"]) == PHRASE_HERAULT,
      h and M.bloc_meteo(h[0], EN["34"]))
    v("phrase du Gard", g and M.bloc_meteo(g[0], EN["30"]) == PHRASE_GARD, g and M.bloc_meteo(g[0], EN["30"]))


# ===================================================== 5 et 6. le moteur lance
def lancer(pluie, date="2026-10-06"):
    """Lance moteur.py comme le workflow, dans un dossier temporaire."""
    t = tempfile.mkdtemp()
    shutil.copy(os.path.join(RACINE, "etat.json"), os.path.join(t, "etat.json"))
    io.open(os.path.join(t, "pluie.json"), "w", encoding="utf-8").write(json.dumps(pluie, ensure_ascii=False))
    env = dict(os.environ, VP_DATE=date, VP_PLUIE=os.path.join(t, "pluie.json"),
               VP_ETAT=os.path.join(t, "etat.json"), VP_EXIGE_ETAT="1",
               VP_DEPTS=os.path.join(RACINE, "depts.json"),
               VP_LIBELLES=os.path.join(RACINE, "libelles-departements.json"), PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, MOTEUR], capture_output=True, text=True, encoding="utf-8", env=env)
    return t, r


def majetat(dossier, sortie_moteur):
    io.open(os.path.join(dossier, "veille.json"), "w", encoding="utf-8").write(sortie_moteur)
    avant = io.open(os.path.join(dossier, "etat.json"), encoding="utf-8").read()
    r = subprocess.run([sys.executable, os.path.join(RACINE, "maj_etat.py"), os.path.join(dossier, "veille.json"),
                        os.path.join(dossier, "etat.json")], capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    apres = io.open(os.path.join(dossier, "etat.json"), encoding="utf-8").read()
    return r, avant != apres, json.loads(apres)


def tous_les_faits(sortie):
    return [f for k, l in sortie.items() if isinstance(l, list) for f in l if isinstance(f, dict) and "cle" in f]


def conditions_reelles():
    print("")
    print("5. Le moteur lance comme par le workflow, au 06/10/2026, sur la reference")
    ref = json.load(io.open(os.path.join(RACINE, "pluie-reference.json"), encoding="utf-8"))
    t, r = lancer(ref)
    v("le moteur tourne", r.returncode == 0, r.stderr.strip()[-120:])
    if r.returncode != 0:
        return
    out = json.loads(r.stdout)
    v("aucune erreur, aucun jour sans donnee dans la fenetre", out["erreurs"] == [] and out["sans_donnee"] == {},
      "%d erreur(s)" % len(out["erreurs"]))
    v("fenetre de 92 jours jusqu'au dernier jour publie",
      out["donnees"]["debut"] == "2026-07-06" and out["donnees"]["fin"] == "2026-10-04"
      and out["donnees"]["attendu"] == "2026-10-04", "%s -> %s" % (out["donnees"]["debut"], out["donnees"]["fin"]))
    v("source declaree : Meteo-France", "Météo-France" in out["source"], out["source"])
    for code, phrase in (("34", PHRASE_HERAULT), ("30", PHRASE_GARD)):
        f = [x for x in out["a_venir"] if x["code"] == code and x["episode"] == "2026-09-30"]
        v("%s : episode du 30/09, mail 1 a venir le 07/10" % EN[code],
          len(f) == 1 and f[0]["mail1_prevu"] == "2026-10-07" and f[0]["etape"] == "a_venir", "")
        if f:
            print("        phrase : %s" % f[0]["bloc_meteo"])
            print("        mention : %s" % f[0]["mention"])
            v("%s : phrase exacte" % EN[code], f[0]["bloc_meteo"] == phrase, "")
            v("%s : mention datee du 6 octobre 2026" % EN[code], f[0]["mention"] == MENTION_0610, "")
    faits = tous_les_faits(out)
    v("chaque fait hors bloque porte sa phrase et sa mention",
      all("bloc_meteo" in f and f.get("mention") for f in faits if f["etape"] != "bloque"), "%d faits" % len(faits))
    texte = r.stdout.lower()
    v("rien d'Open-Meteo, aucun mot interdit dans la sortie",
      "open-meteo" not in texte and not any(w in texte for w in MOTS_INTERDITS), "")
    rm, change, etat = majetat(t, r.stdout)
    v("maj_etat publie : les deux episodes du 30/09 sont dans detection_cron",
      rm.returncode == 0 and change and "34|2026-09-30|A" in etat["detection_cron"]
      and "30|2026-09-30|A" in etat["detection_cron"], "")

    print("")
    print("6. Jours sans donnee")
    pl = copy.deepcopy(ref)
    pl["stations"]["34"]["rr"][-1] = None
    t, r = lancer(pl)
    out = json.loads(r.stdout)
    v("Herault sans le 04/10 : en erreur pour la journee, pas un jour sec",
      [e["depts"] for e in out["erreurs"]] == [["34"]] and out["sans_donnee"] == {"34": ["2026-10-04"]},
      "; ".join(e["erreur"] for e in out["erreurs"]))
    rm, change, _ = majetat(t, r.stdout)
    v("un departement en erreur : maj_etat publie et le signale",
      rm.returncode == 0 and change and "ALERTE" in rm.stdout, "")

    pl = copy.deepcopy(ref)
    pl["stations"]["34"]["rr"][-5] = None                 # le 30/09
    t, r = lancer(pl)
    out = json.loads(r.stdout)
    v("Herault sans le 30/09 : le jour vide ne declenche rien",
      not [f for f in tous_les_faits(out) if f["code"] == "34" and f["episode"] == "2026-09-30"], "")

    pl = copy.deepcopy(ref)
    codes = list(pl["stations"])[:21]
    for c in codes:
        pl["stations"][c]["rr"][-1] = None
    t, r = lancer(pl)
    rm, change, _ = majetat(t, r.stdout)
    v("21 departements sans le 04/10 : maj_etat refuse de publier",
      rm.returncode == 1 and not change and "ECHEC" in rm.stdout, "")

    t, r = lancer(ref, date="2026-10-07")
    out = json.loads(r.stdout)
    rm, change, _ = majetat(t, r.stdout)
    v("Meteo-France n'a pas publie : 96 en erreur, rien n'est publie",
      len(out["erreurs"]) == 96 and rm.returncode == 1 and not change, "%d erreur(s)" % len(out["erreurs"]))


# ================================================================ 7. verif_etat
def verif_etat():
    print("")
    print("7. verif_etat.py")
    r = subprocess.run([sys.executable, os.path.join(RACINE, "verif_etat.py")], capture_output=True, text=True,
                       encoding="utf-8", cwd=RACINE, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    v("etat.json, pluie.json et stations.json passent",
      r.returncode == 0 and all("--- %s" % f in r.stdout for f in ("etat.json", "pluie.json", "stations.json")), "")
    t = tempfile.mkdtemp()
    pl = json.load(io.open(os.path.join(RACINE, "pluie.json"), encoding="utf-8"))
    pl["stations"]["34"]["fichier"] = "contact@exemple.fr"
    p = os.path.join(t, "pluie.json")
    io.open(p, "w", encoding="utf-8").write(json.dumps(pl, ensure_ascii=False))
    r = subprocess.run([sys.executable, os.path.join(RACINE, "verif_etat.py"), p], capture_output=True, text=True,
                       encoding="utf-8", env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    v("une adresse glissee dans pluie.json : commit refuse", r.returncode == 1 and "ECHEC" in r.stdout, "")


def main():
    print("Controle du moteur sur les observations Meteo-France. Aucun acces reseau.")
    print("")
    redaction()
    detection()
    jour_cite()
    reference()
    conditions_reelles()
    verif_etat()
    print("")
    print("RESULTAT : " + ("le moteur est conforme" if OK else "AU MOINS UN ECART — ne pas livrer"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
