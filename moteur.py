#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Moteur de veille pluviometrique Ax'eau - v2.

Deux declencheurs independants, sur les 96 departements metropolitains :
  Serie A - intensite    : un jour a PIC mm ou plus en 24 h
  Serie B - persistance  : NB_JOURS jours de pluie (>= SEUIL_JOUR mm) sur 30 j glissants

Une detection ouvre une SEQUENCE de deux mails :
  mail 1 a J+7 apres l'episode
  mail 2 a 14 jours apres l'ENVOI REEL du mail 1 (pas apres l'episode)

Regles :
  - une seule sequence a la fois par departement
  - apres l'envoi du mail 2, silence de SILENCE jours
  - un mail 1 monte mais jamais envoye expire au bout de EXPIRATION jours

Lecture seule. N'envoie rien, ne programme rien. Sortie JSON sur stdout.
"""
import json, os, sys, time, datetime as dt, urllib.request, urllib.parse

# ---------------------------------------------------------------- parametres
HOST        = os.environ.get("VP_HOST", "historical-forecast-api.open-meteo.com")
PIC         = float(os.environ.get("VP_PIC", 30))        # serie A, mm/24 h
SEUIL_JOUR  = float(os.environ.get("VP_SEUIL_JOUR", 1))  # serie B, mm pour compter un jour de pluie
NB_JOURS    = int(os.environ.get("VP_NB_JOURS", 15))     # serie B, jours dans la fenetre
FENETRE     = 30                                          # fenetre glissante, jours
OFFSET_1    = 7                                           # mail 1 a J+7
ECART_2     = 14                                          # mail 2 a envoi reel du mail 1 + 14
SILENCE     = 30                                          # apres le mail 2
EXPIRATION  = int(os.environ.get("VP_EXPIRATION", 21))    # mail 1 monte non envoye
PROFONDEUR  = int(os.environ.get("VP_PROFONDEUR", 92))
LOT         = 12

AUJOURDHUI  = dt.date.fromisoformat(os.environ["VP_DATE"]) if os.environ.get("VP_DATE") else dt.date.today()

# ---------------------------------------------------------------- etat
# Cle de sequence : "CODE|AAAA-MM-JJ|A" ou "|B"
# etapes : detecte / mail1_monte / mail1_envoye / mail2_monte / mail2_envoye / abandonne
ETAT = {"sequences": {}}
_p = os.environ.get("VP_ETAT")
if _p:
    # Un chemin fourni mais introuvable etait ignore en silence : le moteur
    # repartait d'un etat vide et reproposait des departements deja traites,
    # a chaque tour. Une panne silencieuse qui produit des envois en double
    # est pire qu'un run rouge : on echoue franchement.
    if not os.path.exists(_p):
        sys.exit("VP_ETAT pointe sur un fichier introuvable : %r. "
                 "Le moteur refuse de tourner avec un etat vide." % _p)
    ETAT = json.load(open(_p, encoding="utf-8"))
    ETAT.setdefault("sequences", {})
elif os.environ.get("VP_EXIGE_ETAT"):
    sys.exit("VP_EXIGE_ETAT est pose mais VP_ETAT est absent. "
             "Le moteur refuse de tourner avec un etat vide.")
SEQ = ETAT["sequences"]

# Date de bascule en mode reel, lue dans etat.json. Null tant que le cron
# tourne a blanc.
#
# Tout declencheur dont le mail 1 etait du AVANT cette date est marque
# "abandonne" et non "a_monter" : ecrire a propos d'un orage vieux de deux
# semaines n'a pas de sens. L'abandon n'arme aucun verrou, donc le prochain
# episode reel du departement repart normalement.
#
# La page lit la meme valeur dans le meme fichier : une seule source de verite,
# sans quoi les deux implementations divergeraient des le premier jour.
_b = ETAT.get("bascule")
BASCULE = dt.date.fromisoformat(_b) if _b else None

DEPTS = json.load(open(os.environ.get("VP_DEPTS", "depts.json"), encoding="utf-8"))
DEBUT, FIN = AUJOURDHUI - dt.timedelta(days=PROFONDEUR), AUJOURDHUI


def charger(lot):
    q = urllib.parse.urlencode({
        "latitude":  ",".join(f"{d['lat']}"  for d in lot),
        "longitude": ",".join(f"{d['lon']}" for d in lot),
        "start_date": DEBUT.isoformat(), "end_date": FIN.isoformat(),
        "daily": "precipitation_sum,weather_code", "timezone": "Europe/Paris"})
    with urllib.request.urlopen(f"https://{HOST}/v1/forecast?{q}", timeout=60) as r:
        data = json.load(r)
    return data if isinstance(data, list) else [data]


# Codes WMO -> (libelle complet pour l'outil, mot repris dans le mail ou None).
# 96 et 99 ramenes a "orage" : la grêle est modélisée, pas observée.
PHENO = {95: ("Orage", "orage"), 96: ("Orage avec grêle", "orage"), 99: ("Orage avec forte grêle", "orage"),
         80: ("Averses", "averses"), 81: ("Averses fortes", "averses"), 82: ("Averse violente", "averses"),
         66: ("Pluie verglaçante", None), 67: ("Pluie verglaçante forte", None),
         75: ("Neige forte", None), 85: ("Chutes de neige", None), 86: ("Fortes chutes de neige", None),
         63: ("Pluie continue", None), 65: ("Pluie forte", None), 61: ("Pluie faible", None),
         51: ("Bruine", None), 53: ("Bruine", None), 55: ("Bruine forte", None)}

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


def _mm(v):
    """Millimetres a la francaise. Une valeur entiere ne porte pas de decimale.

    43.8 -> 43,8    34.0 -> 34    108.8 -> 108,8    91.0 -> 91
    """
    return f"{v:.0f}" if abs(v - round(v)) < 1e-9 else f"{v:.1f}".replace(".", ",")


def bloc_meteo(r, dept_en):
    """Phrase exacte injectee dans %%BLOC_METEO%% du template.

    Serie B : forme DATEE. « Sur les 30 derniers jours » est relatif au moment
    de la lecture, alors que le mail part 7 puis 21 jours apres la fin de la
    fenetre observee : au mail 2 le recouvrement tombe a 30 % et la phrase
    devient fausse. Les deux bornes sont donnees explicitement.
    """
    def jour_long(s):
        d = dt.date.fromisoformat(s)
        # Seul le 1er prend « er ». Du 2 au 31 le nombre reste nu.
        return f"{'1er' if d.day == 1 else d.day} {MOIS[d.month - 1]}"
    if r["serie"] == "B":
        return (f"Entre le {jour_long(r['debut_fenetre'])} et le {jour_long(r['episode'])}, "
                f"{r['jours_pluie']} jours de pluie ont été relevés {dept_en}.")
    mot = PHENO.get(r.get("wmo", -1), (None, None))[1]
    mm = _mm(r["pic24_mm"])
    if mot == "orage":
        return f"L'orage du {jour_long(r['pic_date'])} a laissé {mm} mm en 24 heures {dept_en}."
    if mot == "averses":
        return f"Les averses du {jour_long(r['pic_date'])} ont laissé {mm} mm en 24 heures {dept_en}."
    return f"Le {jour_long(r['pic_date'])}, {mm} mm de pluie sont tombés en 24 heures {dept_en}."


def declencheurs(p, dates, codes=None):
    """Jours declencheurs, par serie. Renvoie [(index, serie, detail), ...] chronologique."""
    out = []
    for i, v in enumerate(p):
        if v >= PIC:
            c = codes[i] if codes and i < len(codes) and codes[i] is not None else -1
            out.append((i, "A", {"pic24_mm": round(v, 1), "pic_date": dates[i], "wmo": c,
                                 "phenomene": PHENO.get(c, (None, None))[0]}))
    for i in range(len(p)):
        deb = max(0, i - (FENETRE - 1))
        n = sum(1 for k in range(deb, i + 1) if p[k] >= SEUIL_JOUR)
        if n >= NB_JOURS:
            out.append((i, "B", {"jours_pluie": n, "seuil_jour_mm": SEUIL_JOUR,
                                 "debut_fenetre": dates[deb]}))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def jour(d):
    return (d - AUJOURDHUI).days


def traiter(dept, p, dates, codes=None):
    """Deroule la chronologie d'un departement et renvoie ses sequences."""
    faits = []
    libre_a_partir_de = None   # index de date avant lequel aucune nouvelle sequence
    for i, serie, detail in declencheurs(p, dates, codes):
        episode = dt.date.fromisoformat(dates[i])
        cle = f"{dept['code']}|{dates[i]}|{serie}"
        connue = SEQ.get(cle)

        if not connue and libre_a_partir_de is not None and episode < libre_a_partir_de:
            faits.append({"code": dept["code"], "dept": dept["nom"], "region": dept["region"],
                          "cle": cle, "etape": "bloque", "episode": dates[i], "serie": serie,
                          "libre_le": libre_a_partir_de.isoformat(), **detail})
            continue

        m1_prevu = episode + dt.timedelta(days=OFFSET_1)
        base = {"code": dept["code"], "dept": dept["nom"], "region": dept["region"],
                "cle": cle, "serie": serie, "episode": dates[i],
                "mail1_prevu": m1_prevu.isoformat(), **detail}

        if not connue:
            if BASCULE and m1_prevu < BASCULE:
                faits.append({**base, "etape": "abandonne",
                              "motif": "anterieur a la bascule du " + BASCULE.isoformat()})
                continue                          # n'arme pas le verrou
            if jour(m1_prevu) < -EXPIRATION:
                faits.append({**base, "etape": "expire"})
                continue
            faits.append({**base, "etape": "a_monter" if jour(m1_prevu) <= 0 else "a_venir",
                          "jours": jour(m1_prevu)})
            libre_a_partir_de = m1_prevu + dt.timedelta(days=ECART_2 + SILENCE)
            continue

        e = connue.get("etape")
        base.update({k: v for k, v in connue.items() if k not in ("etape",)})

        if e == "abandonne":
            faits.append({**base, "etape": "abandonne"})
            continue                                  # n'arme pas le verrou

        if e == "mail1_monte":
            age = -jour(dt.date.fromisoformat(connue["mail1_monte_le"]))
            if age > EXPIRATION:
                faits.append({**base, "etape": "expire_non_envoye", "age_jours": age})
                libre_a_partir_de = None
            else:
                faits.append({**base, "etape": "attente_envoi_mail1", "age_jours": age})
                libre_a_partir_de = m1_prevu + dt.timedelta(days=ECART_2 + SILENCE)
            continue

        if e == "mail1_envoye":
            envoi1 = dt.date.fromisoformat(connue["mail1_envoye_le"])
            m2 = envoi1 + dt.timedelta(days=ECART_2)
            faits.append({**base, "etape": "mail2_a_monter" if jour(m2) <= 0 else "mail2_a_venir",
                          "mail2_prevu": m2.isoformat(), "jours": jour(m2)})
            libre_a_partir_de = m2 + dt.timedelta(days=SILENCE)
            continue

        if e == "mail2_monte":
            envoi1 = dt.date.fromisoformat(connue["mail1_envoye_le"])
            m2 = envoi1 + dt.timedelta(days=ECART_2)
            faits.append({**base, "etape": "attente_envoi_mail2", "mail2_prevu": m2.isoformat()})
            libre_a_partir_de = m2 + dt.timedelta(days=SILENCE)
            continue

        if e == "mail2_envoye":
            envoi2 = dt.date.fromisoformat(connue["mail2_envoye_le"])
            fin = envoi2 + dt.timedelta(days=SILENCE)
            faits.append({**base, "etape": "silence" if jour(fin) < 0 else "termine",
                          "silence_jusquau": fin.isoformat()})
            libre_a_partir_de = fin
            continue

        faits.append({**base, "etape": e or "inconnu"})
    return faits


def main():
    tout, erreurs = [], []
    for b in range(0, len(DEPTS), LOT):
        lot = DEPTS[b:b + LOT]
        blocs, msg = None, None
        for essai in range(4):
            try:
                blocs = charger(lot); break
            except Exception as ex:
                msg = str(ex); time.sleep(2 + 3 * essai)
        if blocs is None:
            erreurs.append({"depts": [d["code"] for d in lot], "erreur": msg}); continue
        for d, blk in zip(lot, blocs):
            daily = blk.get("daily") or {}
            dates = daily.get("time", [])
            p = [v or 0.0 for v in daily.get("precipitation_sum", [])]
            codes = daily.get("weather_code", [])
            if not dates:
                erreurs.append({"depts": [d["code"]], "erreur": "pas de donnees"}); continue
            tout.extend(traiter(d, p, dates, codes))

    libelles = {}
    _lp = os.environ.get("VP_LIBELLES", "libelles-departements.json")
    if os.path.exists(_lp):
        libelles = {x["code"]: x["DEPT_EN"] for x in json.load(open(_lp, encoding="utf-8"))}
    for f in tout:
        if f.get("etape") not in ("bloque",):
            f["bloc_meteo"] = bloc_meteo(f, libelles.get(f["code"], "dans le " + f["dept"]))

    par = {}
    for f in tout:
        par.setdefault(f["etape"], []).append(f)
    for k in par:
        par[k].sort(key=lambda r: (r.get("mail1_prevu", ""), r["code"]))

    print(json.dumps({
        "date": AUJOURDHUI.isoformat(), "source": HOST,
        "parametres": {"pic_mm": PIC, "seuil_jour_mm": SEUIL_JOUR, "nb_jours": NB_JOURS,
                       "fenetre_j": FENETRE, "mail1_offset_j": OFFSET_1,
                       "mail2_ecart_j": ECART_2, "silence_j": SILENCE,
                       "expiration_j": EXPIRATION, "profondeur_j": PROFONDEUR},
        "a_faire_aujourdhui": par.get("a_monter", []) + par.get("mail2_a_monter", []),
        "en_attente_envoi": par.get("attente_envoi_mail1", []) + par.get("attente_envoi_mail2", []),
        "a_venir": par.get("a_venir", []) + par.get("mail2_a_venir", []),
        "bloques": par.get("bloque", []), "silence": par.get("silence", []),
        "expires": par.get("expire", []) + par.get("expire_non_envoye", []),
        "abandonnes": par.get("abandonne", []), "termines": par.get("termine", []),
        "erreurs": erreurs}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
