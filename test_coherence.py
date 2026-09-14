#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Controle de non-regression entre moteur.py et index.html.

Le BRIEF impose que la detection et la redaction des deux cotes produisent le
meme resultat : toute modification de l'une doit etre reportee sur l'autre.
Node n'etant pas installe, on ne peut pas executer le JavaScript. On compare
donc les LITTERAUX de phrase des deux cotes apres normalisation des
interpolations, ce qui suffit a garantir « meme texte au caractere pres ».

Cote Python on passe par l'AST et non par une expression reguliere : deux
f-strings adjacentes sur deux lignes forment un seul litteral, qu'une regex
naive coupe en deux.

Verifie aussi :
  - _mm() sur les valeurs de reference
  - la forme datee de la serie B a cheval sur deux mois et sur deux annees
  - qu'aucune phrase ne contient « grele »
  - qu'aucune phrase ne contient de formulation relative au present

Aucun acces reseau. Sortie : code 0 si tout passe, 1 sinon.

Usage :
    .\\run.ps1 test_coherence.py
"""
import ast, io, os, re, sys

sys.stdout.reconfigure(encoding="utf-8")

import moteur

# Ce fichier part dans le depot PUBLIC, ou parametres.py n'existe pas : il ne
# doit dependre que de moteur.py et de la page.
#
# Ses attendus sont ecrits en dur, et c'est voulu : un test qui importe les
# constantes qu'il verifie ne verifie plus rien. Si l'une de ces valeurs change
# ailleurs, ce test doit tomber — c'est son role.
RACINE = os.path.dirname(os.path.abspath(__file__))
PAGE = "index.html"
MOT_GRELE = "grêle"
FORMULATIONS_RELATIVES = ("derniers jours", "dernieres semaines",
                          "dernières semaines", "derniers mois",
                          "recemment", "récemment", "ces derniers")

OK = True


def v(libelle, cond, detail=""):
    global OK
    print("%s | %-52s %s" % ("OK   " if cond else "ECHEC", libelle, detail))
    if not cond:
        OK = False
    return cond


def normaliser(t):
    return re.sub(r"\s+", " ", t).strip()


def texte_expr(e):
    """Squelette textuel d'une expression Python : toute interpolation -> {}."""
    if isinstance(e, ast.JoinedStr):
        out = []
        for x in e.values:
            out.append(str(x.value) if isinstance(x, ast.Constant) else "{}")
        return "".join(out)
    if isinstance(e, ast.Constant) and isinstance(e.value, str):
        return e.value
    return None


def phrases_python():
    src = io.open(os.path.join(RACINE, "moteur.py"), encoding="utf-8").read()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "bloc_meteo")
    out = []
    for noeud in ast.walk(fn):
        if isinstance(noeud, ast.Return) and noeud.value is not None:
            t = texte_expr(noeud.value)
            if t and ("24 heures" in t or "jours de pluie" in t):
                out.append(normaliser(t))
    return out


def phrases_js():
    """Squelette des templates litteraux de blocMeteo(), ${...} -> {}."""
    src = io.open(os.path.join(RACINE, PAGE), encoding="utf-8").read()
    deb = src.index("function blocMeteo(")
    corps = src[deb:src.index("\n}", deb)]
    out = []
    for m in re.findall(r"`([^`]*)`", corps):
        if "24 heures" in m or "jours de pluie" in m:
            out.append(normaliser(re.sub(r"\$\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", "{}", m)))
    return out


def main():
    print("Non-regression moteur.py <-> index.html. Aucun acces reseau.")
    print("")

    # --- 1. Les quatre phrases, au caractere pres -------------------------
    # ast.walk ne respecte pas l'ordre du source : on trie des deux cotes,
    # l'ordre des return n'a aucune portee metier.
    py, js = sorted(phrases_python()), sorted(phrases_js())
    v("4 phrases trouvees dans moteur.py", len(py) == 4, "%d trouvee(s)" % len(py))
    v("4 phrases trouvees dans index.html", len(js) == 4, "%d trouvee(s)" % len(js))
    for i, (a, b) in enumerate(zip(py, js), start=1):
        v("phrase %d identique des deux cotes" % i, a == b,
          a[:58] if a == b else "\n      py : %s\n      js : %s" % (a, b))
    ecart = set(py) ^ set(js)
    v("aucune phrase presente d'un seul cote", not ecart,
      "; ".join(sorted(ecart)) if ecart else "")

    # --- 2. _mm() ---------------------------------------------------------
    print("")
    for val, attendu in ((43.8, "43,8"), (34.0, "34"), (108.8, "108,8"),
                         (91.0, "91"), (30.0, "30"), (0.0, "0"), (40.6, "40,6")):
        got = moteur._mm(val)
        v("_mm(%s) -> %s" % (val, attendu), got == attendu, "obtenu %s" % got)

    # --- 3. Serie B datee, cas limites -----------------------------------
    print("")
    cas = [
        ("dans le mois", "2026-02-06", "2026-03-07",
         "Entre le 6 février et le 7 mars, 15 jours de pluie ont été relevés dans le Finistère."),
        ("a cheval sur deux annees", "2025-12-14", "2026-01-12",
         "Entre le 14 décembre et le 12 janvier, 15 jours de pluie ont été relevés dans le Finistère."),
        ("fin decembre -> debut janvier", "2025-12-31", "2026-01-01",
         "Entre le 31 décembre et le 1er janvier, 15 jours de pluie ont été relevés dans le Finistère."),
        ("annee bissextile", "2028-02-01", "2028-02-29",
         "Entre le 1er février et le 29 février, 15 jours de pluie ont été relevés dans le Finistère."),
    ]
    for libelle, d1, d2, attendu in cas:
        got = moteur.bloc_meteo({"serie": "B", "jours_pluie": 15,
                                 "debut_fenetre": d1, "episode": d2}, "dans le Finistère")
        v("serie B, %s" % libelle, got == attendu, "" if got == attendu else "\n      obtenu : " + got)

    # --- 3 bis. Le « 1er » : les cinq endroits ou une date est ecrite -----
    # jour_long() est appelee a cinq endroits : les trois formes de la serie A,
    # et les deux bornes de la serie B. Un cas par endroit.
    print("")
    lib13 = "dans les Bouches-du-Rhône"
    cas_1er = [
        ("série A orage, date au 1er", {"serie": "A", "wmo": 95, "pic24_mm": 38.8,
                                        "pic_date": "2026-08-01"},
         "L'orage du 1er août a laissé 38,8 mm en 24 heures " + lib13 + "."),
        ("série A averses, date au 1er", {"serie": "A", "wmo": 81, "pic24_mm": 34.0,
                                          "pic_date": "2026-10-01"},
         "Les averses du 1er octobre ont laissé 34 mm en 24 heures " + lib13 + "."),
        ("série A neutre, date au 1er", {"serie": "A", "wmo": 63, "pic24_mm": 40.6,
                                         "pic_date": "2026-02-01"},
         "Le 1er février, 40,6 mm de pluie sont tombés en 24 heures " + lib13 + "."),
        ("série B, borne de début au 1er", {"serie": "B", "jours_pluie": 15,
                                            "debut_fenetre": "2026-02-01",
                                            "episode": "2026-03-02"},
         "Entre le 1er février et le 2 mars, 15 jours de pluie ont été relevés " + lib13 + "."),
        ("série B, borne de fin au 1er", {"serie": "B", "jours_pluie": 15,
                                          "debut_fenetre": "2026-02-02",
                                          "episode": "2026-03-01"},
         "Entre le 2 février et le 1er mars, 15 jours de pluie ont été relevés " + lib13 + "."),
    ]
    for libelle, r, attendu in cas_1er:
        got = moteur.bloc_meteo(r, lib13)
        v(libelle, got == attendu, "" if got == attendu else "\n      obtenu : " + got)

    # Du 2 au 31 le nombre reste nu : seul le 1er prend « er ».
    for jour in (2, 11, 21, 31):
        got = moteur.bloc_meteo({"serie": "A", "wmo": 63, "pic24_mm": 40.6,
                                 "pic_date": "2026-03-%02d" % jour}, lib13)
        attendu = "Le %d mars," % jour
        v("le %d mars reste nu" % jour, got.startswith(attendu), got[:22])
    v("aucun « 2er », « 11er », « 21er », « 31er »",
      not any("er mars" in moteur.bloc_meteo(
          {"serie": "A", "wmo": 63, "pic24_mm": 40.6, "pic_date": "2026-03-%02d" % j}, lib13)
          for j in (2, 11, 21, 31)), "")

    # --- 4. Grele, formulations relatives, decimale parasite --------------
    print("")
    echantillon, lib = [], "dans les Bouches-du-Rhône"
    for wmo in sorted(moteur.PHENO) + [-1, 63]:
        for mm in (38.8, 34.0):
            echantillon.append(moteur.bloc_meteo(
                {"serie": "A", "wmo": wmo, "pic24_mm": mm, "pic_date": "2026-08-20"}, lib))
    echantillon.append(moteur.bloc_meteo(
        {"serie": "B", "jours_pluie": 18, "debut_fenetre": "2026-01-05",
         "episode": "2026-02-03"}, lib))

    avec_grele = [p for p in echantillon if MOT_GRELE in p.lower()]
    v("aucune phrase ne contient « grêle »", not avec_grele,
      "%d phrase(s) testee(s)" % len(echantillon) if not avec_grele else avec_grele[0])

    avec_rel = [p for p in echantillon
                if any(f in p.lower() for f in FORMULATIONS_RELATIVES)]
    v("aucune formulation relative au présent", not avec_rel,
      "%d phrase(s) testee(s)" % len(echantillon) if not avec_rel else avec_rel[0])

    avec_zero = [p for p in echantillon if re.search(r"\d+,0(?!\d)\s*mm", p)]
    v("aucune valeur en mm terminée par « ,0 »", not avec_zero,
      "%d phrase(s) testee(s)" % len(echantillon) if not avec_zero else avec_zero[0])

    # --- 5. Les codes grele restent ramenes a « orage » -------------------
    for wmo in (96, 99):
        p = moteur.bloc_meteo({"serie": "A", "wmo": wmo, "pic24_mm": 38.8,
                               "pic_date": "2026-08-20"}, lib)
        v("code WMO %d ramene a « orage »" % wmo, p.startswith("L'orage du"), p[:40])

    # --- 6. La regle de bascule, presente et symetrique -------------------
    # Ajoutee le 14/09/2026. Un declencheur dont le mail 1 etait du avant le
    # passage en reel doit etre abandonne des deux cotes, sans armer de verrou.
    print("")
    py_src = io.open(os.path.join(RACINE, "moteur.py"), encoding="utf-8").read()
    js_src = io.open(os.path.join(RACINE, PAGE), encoding="utf-8").read()

    for libelle, dans_py, dans_js in (
        ("la date de bascule est lue dans etat.json",
         'ETAT.get("bascule")' in py_src, "e.bascule" in js_src),
        ("un declencheur anterieur est marque abandonne",
         '"etape": "abandonne"' in py_src, "etape:'abandonne'" in js_src),
        ("le motif nomme la bascule",
         "anterieur a la bascule" in py_src, "anterieur a la bascule" in js_src),
        ("l'abandon n'arme aucun verrou",
         "n'arme pas le verrou" in py_src, "n'arme aucun verrou" in js_src),
    ):
        v(libelle, dans_py and dans_js,
          "python %s, page %s" % ("oui" if dans_py else "NON",
                                  "oui" if dans_js else "NON"))

    # L'abandon ne doit jamais poser libre_a_partir_de : on verifie que la
    # branche se termine par un continue sans affectation de verrou.
    i = py_src.find('"etape": "abandonne",')
    bloc = py_src[i:i + 400] if i > 0 else ""
    v("branche d'abandon sans armement de verrou",
      bool(bloc) and "libre_a_partir_de" not in bloc.split("continue")[0],
      "verifie sur la branche de moteur.py")

    print("")
    print("RESULTAT : " + ("moteur.py et index.html sont alignes"
                           if OK else "AU MOINS UN ECART — ne pas livrer"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
