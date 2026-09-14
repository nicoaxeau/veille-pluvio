#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Garde-fou de etat.json avant tout commit. LE DEPOT EST PUBLIC.

Regle absolue : aucune adresse email ne doit figurer dans le depot. Ce script
est ce qui nous protege du jour ou quelqu'un ajoutera un champ sans y penser.

Controle dur : aucune chaine de etat.json, cle ou valeur, a quelque profondeur
que ce soit, ne contient un « @ » suivi d'un point. S'il en trouve une, le
script sort en erreur et le workflow ne commite pas.

Controle d'alerte : les champs de « campagnes » sont compares a une liste
blanche. Un champ inconnu ne fait pas echouer, mais il est signale : c'est
souvent le signe qu'on a recopie une reponse Mailjet telle quelle au lieu de
n'en extraire que les compteurs agreges.

Aucun acces reseau. Sortie : code 0 si etat.json peut etre commite, 1 sinon.

Usage :
    python verif_etat.py
    python verif_etat.py chemin/vers/etat.json
"""
import io, json, os, re, sys

sys.stdout.reconfigure(encoding="utf-8")

# « un @ suivi d'un point » — volontairement large.
ADRESSE = re.compile(r"@[^\s@]*\.")

# Ce que la page consomme, et rien de plus. Jamais le detail d'un
# destinataire, meme anonymise : si Mailjet renvoie la liste des contacts
# ayant ouvert ou clique, on l'ignore.
CHAMPS_CAMPAGNE = {"id", "dept", "nom_dept", "serie", "episode", "etape",
                   "cle", "monte_le", "envoye_le", "mail", "stats", "liste_id",
                   "objet", "titre"}
CHAMPS_STATS = {"contacts", "delivres", "ouvertures", "clics", "desabos"}

# Un champ dont le nom evoque un destinataire n'a rien a faire ici, meme vide.
NOMS_SUSPECTS = ("email", "mail_", "contact_email", "adresse", "destinataire",
                 "recipient", "subscriber", "opener", "clicker")


def parcourir(noeud, chemin=""):
    """Rend (chemin, texte) pour chaque chaine du document, cles comprises."""
    if isinstance(noeud, dict):
        for k, v in noeud.items():
            yield chemin + "/" + str(k), str(k)
            yield from parcourir(v, chemin + "/" + str(k))
    elif isinstance(noeud, list):
        for i, v in enumerate(noeud):
            yield from parcourir(v, chemin + "[%d]" % i)
    elif isinstance(noeud, str):
        yield chemin, noeud


def main():
    chemin = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "etat.json")

    print("Controle de %s avant commit. LE DEPOT EST PUBLIC." % os.path.basename(chemin))
    print("")

    if not os.path.exists(chemin):
        print("ECHEC | fichier introuvable : %s" % chemin)
        return 1
    try:
        etat = json.load(io.open(chemin, encoding="utf-8"))
    except ValueError as e:
        print("ECHEC | JSON illisible : %s" % e)
        return 1

    dur = True

    # --- Controle dur : aucune adresse, nulle part -----------------------
    trouvees = [(c, t) for c, t in parcourir(etat) if ADRESSE.search(t)]
    if trouvees:
        dur = False
        print("ECHEC | %d chaine(s) contenant un « @ » suivi d'un point :" % len(trouvees))
        for c, t in trouvees[:10]:
            print("        %s = %s" % (c, t[:60]))
        print("")
        print("        RIEN N'EST COMMITE. Le depot est public : aucune adresse")
        print("        email ne doit y figurer, meme dans un champ technique.")
    else:
        print("OK    | aucune chaine ne contient un « @ » suivi d'un point")

    # --- Controle dur : aucun nom de champ evoquant un destinataire ------
    suspects = sorted({c for c, t in parcourir(etat)
                       if any(n in c.lower() for n in NOMS_SUSPECTS)})
    if suspects:
        dur = False
        print("ECHEC | %d champ(s) au nom evoquant un destinataire :" % len(suspects))
        for c in suspects[:10]:
            print("        %s" % c)
    else:
        print("OK    | aucun champ au nom evoquant un destinataire")

    # --- Alerte : champs hors liste blanche ------------------------------
    inconnus, stats_inconnues = set(), set()
    for cid, c in (etat.get("campagnes") or {}).items():
        if not isinstance(c, dict):
            continue
        inconnus |= set(c) - CHAMPS_CAMPAGNE
        s = c.get("stats")
        if isinstance(s, dict):
            stats_inconnues |= set(s) - CHAMPS_STATS
    if inconnus or stats_inconnues:
        print("ALERTE| champ(s) hors liste blanche, a verifier :")
        for x in sorted(inconnus):
            print("        campagnes/*/%s" % x)
        for x in sorted(stats_inconnues):
            print("        campagnes/*/stats/%s" % x)
        print("        Ne mettre dans etat.json que ce dont la page a besoin :")
        print("        departement, serie, dates, identifiants, compteurs agreges.")
    else:
        print("OK    | tous les champs de campagnes sont en liste blanche")

    # --- Information ------------------------------------------------------
    print("")
    print("  version %s   maj %s" % (etat.get("version"), etat.get("maj")))
    print("  %d sequence(s), %d campagne(s), %d detection(s) du cron"
          % (len(etat.get("sequences") or {}), len(etat.get("campagnes") or {}),
             len(etat.get("detection_cron") or {})))
    print("  %d octets" % os.path.getsize(chemin))

    print("")
    print("RESULTAT : " + ("etat.json peut etre commite"
                           if dur else "COMMIT REFUSE"))
    return 0 if dur else 1


if __name__ == "__main__":
    sys.exit(main())
