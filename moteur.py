#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Moteur de veille pluviometrique Ax'eau - v3, observations Meteo-France.

Deux declencheurs independants, sur les 96 departements metropolitains, calcules
a UNE station par departement : la station Meteo-France la plus proche de la
prefecture, dans le departement (stations.json, liste figee).
  Serie A - intensite    : un jour a PIC mm ou plus en 24 h a cette station
  Serie B - persistance  : NB_JOURS jours de pluie (>= SEUIL_JOUR mm) sur 30 j
                           glissants a cette station

La pluie est lue dans pluie.json, produit chaque matin par
extraction_meteofrance.py. La journee J de Meteo-France va de 06 h UTC le jour
J a 06 h UTC le jour J+1 : les dates sont reprises telles quelles.

Un jour sans donnee (null) ne declenche rien, ne compte pas comme jour de
pluie, et met le departement en erreur pour ce jour. Jamais 0 : un jour sans
donnee est une erreur, pas un jour sec.

Une detection ouvre une SEQUENCE de deux mails :
  mail 1 a J+7 apres l'episode
  mail 2 a 14 jours apres l'ENVOI REEL du mail 1 (pas apres l'episode)

Regles :
  - une seule sequence a la fois par departement
  - apres l'envoi du mail 2, silence de SILENCE jours
  - un mail 1 monte mais jamais envoye expire au bout de EXPIRATION jours

La phrase de serie A cite le jour le plus fort de l'episode, parmi les jours
consecutifs a PIC mm ou plus, deja connu au moment du mail 1. Valeurs arrondies
au millimetre, la demie vers le haut.

Lecture seule. N'envoie rien, ne programme rien. Sortie JSON sur stdout.
"""
import json, math, os, sys, datetime as dt

# ---------------------------------------------------------------- parametres
PIC         = float(os.environ.get("VP_PIC", 30))        # serie A, mm/24 h
SEUIL_JOUR  = float(os.environ.get("VP_SEUIL_JOUR", 1))  # serie B, mm pour compter un jour de pluie
NB_JOURS    = int(os.environ.get("VP_NB_JOURS", 15))     # serie B, jours dans la fenetre
FENETRE     = 30                                          # fenetre glissante, jours
OFFSET_1    = 7                                           # mail 1 a J+7
ECART_2     = 14                                          # mail 2 a envoi reel du mail 1 + 14
SILENCE     = 30                                          # apres le mail 2
EXPIRATION  = int(os.environ.get("VP_EXPIRATION", 21))    # mail 1 monte non envoye
PROFONDEUR  = int(os.environ.get("VP_PROFONDEUR", 92))
# Meteo-France publie la pluie du jour J le matin du jour J+2.
DELAI_PUBLICATION = 2
# Au mail 1, a J+7, les journees connues vont donc jusqu'a J+5.
CONNU_AU_MAIL1 = OFFSET_1 - DELAI_PUBLICATION

PLUIE       = os.environ.get("VP_PLUIE", "pluie.json")
SOURCE      = "Météo-France, Données climatologiques de base - quotidiennes (pluie.json)"
# Decision de Nicolas du 06/10/2026 : la licence impose la source ET la date de
# mise a jour. La date est celle du fichier Meteo-France qui a servi.
MENTION     = "Données pluviométriques : Météo-France, mise à jour du %s"

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
DEBUT = AUJOURDHUI - dt.timedelta(days=PROFONDEUR)

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


# ---------------------------------------------------------------- redaction
def _mm(v):
    """Millimetres arrondis au millimetre, la demie vers le haut.

    146.0 -> 146    72.4 -> 72    212.5 -> 213

    Meme regle que Math.round dans la page. round() de Python arrondirait
    212.5 a 212 (au pair) : les deux implementations divergeraient.
    """
    return str(int(math.floor(v + 0.5)))


def jour_long(s):
    """« 30 septembre », « 1er octobre ». Seul le 1er prend « er »."""
    d = dt.date.fromisoformat(s)
    return f"{'1er' if d.day == 1 else d.day} {MOIS[d.month - 1]}"


def date_paris(iso_utc):
    """Date a Paris d'un instant UTC. Heure d'ete du dernier dimanche de mars au
    dernier dimanche d'octobre, a 01 h UTC. Meme regle que l'extraction."""
    t = dt.datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ")

    def dernier_dimanche(annee, mois):
        d = dt.date(annee, mois, 31)
        return d - dt.timedelta(days=(d.weekday() + 1) % 7)

    ete = (dt.datetime.combine(dernier_dimanche(t.year, 3), dt.time(1)) <= t
           < dt.datetime.combine(dernier_dimanche(t.year, 10), dt.time(1)))
    return (t + dt.timedelta(hours=2 if ete else 1)).date()


def mention(publie_le):
    """Mention de source du mail, datee de la publication du fichier
    Meteo-France qui a servi a la phrase. None si la date est inconnue."""
    if not publie_le:
        return None
    d = date_paris(publie_le)
    return MENTION % f"{'1er' if d.day == 1 else d.day} {MOIS[d.month - 1]} {d.year}"


def bloc_meteo(r, dept_en):
    """Phrase exacte injectee dans %%BLOC_METEO%% du template.

    Serie A : une seule forme, sans « orage » ni « averses » : Meteo-France ne
    les fournit pas de facon fiable. Le jour et la valeur sont ceux du jour le
    plus fort de l'episode (cite_date, cite_mm).

    Serie B : forme DATEE. « Sur les 30 derniers jours » est relatif au moment
    de la lecture, alors que le mail part 7 puis 21 jours apres la fin de la
    fenetre observee : au mail 2 le recouvrement tombe a 30 % et la phrase
    devient fausse. Les deux bornes sont donnees explicitement.
    """
    if r["serie"] == "B":
        return (f"Entre le {jour_long(r['debut_fenetre'])} et le {jour_long(r['episode'])}, "
                f"{r['jours_pluie']} jours de pluie ont été relevés {dept_en}.")
    return (f"Le {jour_long(r['cite_date'])}, {_mm(r['cite_mm'])} mm de pluie "
            f"sont tombés en 24 heures {dept_en}.")


# ---------------------------------------------------------------- detection
def declencheurs(p, dates):
    """Jours declencheurs, par serie. Renvoie [(index, serie, detail), ...] chronologique.

    p : pluie du jour en mm, None quand il n'y a pas de donnee. Un jour sans
    donnee ne declenche rien, et ne compte pas comme jour de pluie.
    """
    out = []
    for i, v in enumerate(p):
        if v is not None and v >= PIC:
            out.append((i, "A", {"pic24_mm": round(v, 1), "pic_date": dates[i]}))
    for i in range(len(p)):
        if p[i] is None:
            continue
        deb = max(0, i - (FENETRE - 1))
        n = sum(1 for k in range(deb, i + 1) if p[k] is not None and p[k] >= SEUIL_JOUR)
        if n >= NB_JOURS:
            out.append((i, "B", {"jours_pluie": n, "seuil_jour_mm": SEUIL_JOUR,
                                 "debut_fenetre": dates[deb]}))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def jour_cite(p, dates, i, libre=None):
    """Le jour que cite le mail : le plus fort des jours consecutifs a PIC mm ou
    plus autour du declenchement i, sans remonter dans le verrou precedent
    (libre = premier jour libre du departement), et deja connu au moment du
    mail 1. Un jour sans donnee interrompt l'episode. A egalite, le plus tot.
    Renvoie (date, valeur)."""
    fort = lambda k: p[k] is not None and p[k] >= PIC
    k0 = i
    while k0 > 0 and fort(k0 - 1) and (libre is None or dt.date.fromisoformat(dates[k0 - 1]) >= libre):
        k0 -= 1
    k1 = i
    while k1 + 1 < len(p) and k1 + 1 <= i + CONNU_AU_MAIL1 and fort(k1 + 1):
        k1 += 1
    best = max(range(k0, k1 + 1), key=lambda k: (p[k], -k))
    return dates[best], p[best]


def jour(d):
    return (d - AUJOURDHUI).days


def traiter(dept, p, dates):
    """Deroule la chronologie d'un departement et renvoie ses sequences."""
    faits = []
    libre_a_partir_de = None   # date avant laquelle aucune nouvelle sequence
    for i, serie, detail in declencheurs(p, dates):
        episode = dt.date.fromisoformat(dates[i])
        cle = f"{dept['code']}|{dates[i]}|{serie}"
        connue = SEQ.get(cle)
        if serie == "A":
            detail = dict(detail)
            detail["cite_date"], detail["cite_mm"] = jour_cite(p, dates, i, libre_a_partir_de)

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
            # En silence avant fin ; termine des fin, le jour ou le verrou tombe.
            faits.append({**base, "etape": "silence" if jour(fin) > 0 else "termine",
                          "silence_jusquau": fin.isoformat()})
            libre_a_partir_de = fin
            continue

        faits.append({**base, "etape": e or "inconnu"})
    return faits


def simuler(p, dates, depuis=0, jusqu_a=None):
    """Ce que compte l'onglet Simulation de la page : les sequences qu'auraient
    ouvertes les declencheurs, mails partis a l'heure. Demarrage a froid a
    l'indice depuis, aucun verrou herite ; declencheurs retenus jusqu'a l'indice
    jusqu_a inclus. Un departement est libre a l'episode + 51 jours."""
    jusqu_a = len(p) - 1 if jusqu_a is None else jusqu_a
    seqs, libre = [], None
    for i, serie, detail in declencheurs(p, dates):
        if i < depuis or i > jusqu_a:
            continue
        e = dt.date.fromisoformat(dates[i])
        if libre is not None and e < libre:
            continue
        x = {"episode": dates[i], "serie": serie, **detail}
        if serie == "A":
            x["cite_date"], x["cite_mm"] = jour_cite(p, dates, i, libre)
        seqs.append(x)
        libre = e + dt.timedelta(days=OFFSET_1 + ECART_2 + SILENCE)
    return seqs


# ---------------------------------------------------------------- donnees
def lire_pluie(chemin=PLUIE):
    """pluie.json -> (document, dates). Les null restent None."""
    doc = json.load(open(chemin, encoding="utf-8"))
    d0, d1 = dt.date.fromisoformat(doc["debut"]), dt.date.fromisoformat(doc["fin"])
    dates = [(d0 + dt.timedelta(days=k)).isoformat() for k in range((d1 - d0).days + 1)]
    return doc, dates


def main():
    # Sortie JSON en UTF-8 sur toutes les plateformes : la console Windows ecrit
    # sinon en cp1252, et les accents de la phrase deviennent illisibles.
    sys.stdout.reconfigure(encoding="utf-8")
    doc, dates_tout = lire_pluie()
    # Fenetre de detection : PROFONDEUR jours, jusqu'au dernier jour publie.
    debut = max(DEBUT.isoformat(), dates_tout[0])
    fin = min(AUJOURDHUI.isoformat(), dates_tout[-1])
    i0, i1 = dates_tout.index(debut), dates_tout.index(fin)
    dates = dates_tout[i0:i1 + 1]
    # Le jour qui devrait etre publie aujourd'hui. Un departement qui ne l'a
    # pas est en erreur pour la journee : fichier en retard ou absent, ou
    # station silencieuse. Il sera rattrape au tour suivant.
    attendu = (AUJOURDHUI - dt.timedelta(days=DELAI_PUBLICATION)).isoformat()

    tout, erreurs, sans_donnee = [], [], {}
    for d in DEPTS:
        s = (doc.get("stations") or {}).get(d["code"])
        if not s:
            erreurs.append({"depts": [d["code"]], "erreur": "station absente de pluie.json"})
            continue
        p = s["rr"][i0:i1 + 1]
        manquants = [j for j, v in zip(dates, p) if v is None]
        if manquants:
            sans_donnee[d["code"]] = manquants
        if attendu > dates[-1] or p[dates.index(attendu)] is None:
            erreurs.append({"depts": [d["code"]],
                            "erreur": "pas de donnee le %s (fichier %s, station silencieuse depuis %s j)"
                                      % (attendu, s.get("etat"), s.get("silence_j"))})
        m = mention(s.get("publie_le"))
        for f in traiter(d, p, dates):
            f["mention"] = m
            tout.append(f)

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
        "date": AUJOURDHUI.isoformat(), "source": SOURCE,
        "donnees": {"debut": dates[0], "fin": dates[-1], "attendu": attendu,
                    "mention": doc.get("mention")},
        "parametres": {"pic_mm": PIC, "seuil_jour_mm": SEUIL_JOUR, "nb_jours": NB_JOURS,
                       "fenetre_j": FENETRE, "mail1_offset_j": OFFSET_1,
                       "mail2_ecart_j": ECART_2, "silence_j": SILENCE,
                       "expiration_j": EXPIRATION, "profondeur_j": PROFONDEUR,
                       "connu_au_mail1_j": CONNU_AU_MAIL1},
        "a_faire_aujourdhui": par.get("a_monter", []) + par.get("mail2_a_monter", []),
        "en_attente_envoi": par.get("attente_envoi_mail1", []) + par.get("attente_envoi_mail2", []),
        "a_venir": par.get("a_venir", []) + par.get("mail2_a_venir", []),
        "bloques": par.get("bloque", []), "silence": par.get("silence", []),
        "expires": par.get("expire", []) + par.get("expire_non_envoye", []),
        "abandonnes": par.get("abandonne", []), "termines": par.get("termine", []),
        "erreurs": erreurs, "sans_donnee": sans_donnee}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
