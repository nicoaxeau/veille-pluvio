#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Met a jour etat.json a partir de la sortie de moteur.py. MODE A BLANC.

Le cron detecte, il ecrit etat.json, et c'est tout. Il ne monte aucun
brouillon, il n'appelle ni Mailjet ni Vision.

Ce qui est ecrit :
  maj              horodatage de la derniere execution
  detection_cron   les declencheurs vus par le cron, indexes par cle de
                   sequence. La page compare ses propres detections a
                   celles-ci et affiche une banniere si elles divergent.
  parametres       les reglages qui ont servi, pour que la page sache si
                   elle tourne avec les memes

Ce qui n'est PAS touche en mode a blanc :
  sequences        creer une sequence sans envoyer de mail la ferait expirer
                   au bout de 21 jours et bloquerait le departement pour rien
  campagnes        aucune campagne n'est montee

AUCUNE ADRESSE EMAIL n'entre ici : le depot est public. verif_etat.py le
verifie avant chaque commit.

Usage :
    python moteur.py > veille.json && python maj_etat.py veille.json
    python moteur.py | python maj_etat.py -
"""
import datetime as dt
import io, json, os, sys

sys.stdout.reconfigure(encoding="utf-8")

MODE_A_BLANC = True

# Au-dela, le balayage est trop partiel pour etre publie comme un etat.
MAX_DEPTS_EN_ERREUR = 20

RACINE = os.path.dirname(os.path.abspath(__file__))
ETAT = os.path.join(RACINE, "etat.json")

# Les etapes qu'on ne considere pas comme une detection active. La page fait
# le meme filtre, sans quoi la comparaison signalerait une fausse divergence.
ETAPES_IGNOREES = ("bloque", "expire")

# Champs retenus par declencheur. Volontairement court : la page n'utilise
# que les cles, le reste ne sert qu'au diagnostic.
CHAMPS = ("dept", "serie", "episode", "etape")


def charger_veille(source):
    if source == "-":
        return json.load(sys.stdin)
    return json.load(io.open(source, encoding="utf-8"))


def main():
    if len(sys.argv) < 2:
        print("Usage : maj_etat.py <sortie de moteur.py | ->")
        return 2

    print("Mise a jour de etat.json — MODE A BLANC." if MODE_A_BLANC
          else "Mise a jour de etat.json.")
    print("Aucun appel Mailjet, aucun appel Vision, aucun brouillon monte.")
    print("")

    veille = charger_veille(sys.argv[1])

    erreurs = veille.get("erreurs") or []
    depts_en_erreur = sum(len(e.get("depts") or []) for e in erreurs)
    if depts_en_erreur > MAX_DEPTS_EN_ERREUR:
        print("ECHEC | %d departements en erreur chez Open-Meteo (max %d)."
              % (depts_en_erreur, MAX_DEPTS_EN_ERREUR))
        print("        Le balayage est trop partiel pour etre publie. etat.json")
        print("        n'est pas modifie.")
        return 1
    if erreurs:
        print("ALERTE| %d departement(s) en erreur, balayage partiel." % depts_en_erreur)

    etat = json.load(io.open(ETAT, encoding="utf-8"))
    avant = json.dumps(etat, ensure_ascii=False, sort_keys=True)

    # --- Les declencheurs vus par le cron --------------------------------
    detection = {}
    for categorie, faits in veille.items():
        if not isinstance(faits, list):
            continue
        for f in faits:
            if not isinstance(f, dict) or "cle" not in f:
                continue
            if f.get("etape") in ETAPES_IGNOREES:
                continue
            detection[f["cle"]] = {k: f.get(k) for k in CHAMPS if f.get(k) is not None}

    etat["detection_cron"] = dict(sorted(detection.items()))
    etat["parametres"] = veille.get("parametres", etat.get("parametres"))
    etat["maj"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()

    if MODE_A_BLANC:
        # Explicite : on ne cree ni sequence ni campagne.
        etat.setdefault("sequences", {})
        etat.setdefault("campagnes", {})
        etat["mode"] = "a_blanc"

    apres = json.dumps(etat, ensure_ascii=False, sort_keys=True)
    io.open(ETAT, "w", encoding="utf-8", newline="\n").write(
        json.dumps(etat, ensure_ascii=False, indent=1) + "\n")

    par_etape = {}
    for f in detection.values():
        par_etape[f.get("etape", "?")] = par_etape.get(f.get("etape", "?"), 0) + 1

    print("OK    | date de detection      %s" % veille.get("date"))
    print("OK    | declencheurs retenus   %d" % len(detection))
    for e, n in sorted(par_etape.items()):
        print("        %-22s %d" % (e, n))
    print("OK    | sequences inchangees   %d" % len(etat.get("sequences") or {}))
    print("OK    | campagnes inchangees   %d" % len(etat.get("campagnes") or {}))
    print("OK    | etat.json              %d octets" % os.path.getsize(ETAT))
    print("")
    print("etat.json %s." % ("modifie" if avant != apres else "inchange"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
