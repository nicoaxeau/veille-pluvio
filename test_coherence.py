#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Controle de non-regression entre moteur.py et la page (detection.js).

La detection existe deux fois : en Python dans moteur.py, en JavaScript dans
detection.js, que charge index.html. Ce controle fait tourner les deux sur les
memes donnees et exige le meme resultat, a l'unite :

  1. la redaction : phrases, arrondis, « 1er », mentions datees a Paris ;
  2. le calcul, sur des cas fabriques : jour sans donnee, jour cite, verrou,
     bascule ;
  3. pluie-reference.json : declencheurs et jours cites des 96 departements,
     et la simulation de douze mois (236 sequences, 472 campagnes) ;
  4. le moteur lance comme par le workflow, a deux dates, dont une avec des
     sequences dans tous les etats et une date de bascule : memes lignes,
     memes etapes, memes phrases, memes mentions, memes erreurs ;
  5. pluie.json, le fichier du jour, a la date du jour ;
  6. la page : elle charge detection.js avec une empreinte a jour, et ne
     refait pas le calcul ; ses departements et ses prepositions sont ceux du
     moteur ; elle ne charge aucune ressource exterieure ; aucune phrase ne
     contient « orage », « averses », « grele » ou « jusqu'a ».

Le JavaScript tourne sous Node s'il est installe, c'est le cas sur GitHub ;
sinon, en local, dans Chrome sans fenetre. Sur GitHub, l'absence de Node fait
echouer le controle au lieu de le sauter.

Aucun acces reseau. Rien n'est ecrit dans le depot. Sortie : code 0 si tout
passe, 1 sinon.

Usage :
    python test_coherence.py [chemin de moteur.py] [chemin de detection.js]
"""
import datetime as dt, hashlib, html, importlib.util, io, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.dont_write_bytecode = True

RACINE = os.path.dirname(os.path.abspath(__file__))
MOTEUR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RACINE, "moteur.py")
DETECTION = sys.argv[2] if len(sys.argv) > 2 else os.path.join(RACINE, "detection.js")
PAGE = os.path.join(RACINE, "index.html")
for _k in ("VP_ETAT", "VP_EXIGE_ETAT", "VP_PIC", "VP_SEUIL_JOUR", "VP_NB_JOURS",
           "VP_DATE", "VP_PLUIE", "VP_PROFONDEUR", "VP_EXPIRATION"):
    os.environ.pop(_k, None)
os.environ["VP_DEPTS"] = os.path.join(RACINE, "depts.json")

_spec = importlib.util.spec_from_file_location("moteur", MOTEUR)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def lire(nom):
    return json.load(io.open(os.path.join(RACINE, nom), encoding="utf-8"))


DEPTS = [{"code": d["code"], "nom": d["nom"], "region": d["region"]} for d in lire("depts.json")]
LIBELLES = {x["code"]: x["DEPT_EN"] for x in lire("libelles-departements.json")}
REFERENCE = lire("pluie-reference.json")
DU_JOUR = lire("pluie.json") if os.path.exists(os.path.join(RACINE, "pluie.json")) else None
SEQUENCES_REFERENCE = lire("sequences-reference.json")

# Attendus ecrits en dur, et c'est voulu : un controle qui importe ce qu'il
# verifie ne verifie plus rien.
PERIODE = ("2025-10-01", "2026-09-30")
PERIODES_SIMULATION = {"2026-10-04": ("2025-10-01", "2026-09-30"), "2026-09-30": ("2025-10-01", "2026-09-30"),
                       "2027-01-03": ("2026-01-01", "2026-12-31"), "2027-01-31": ("2026-02-01", "2027-01-31"),
                       "2028-03-01": ("2027-03-01", "2028-02-29")}
MOTS_INTERDITS = ("orage", "averse", "grêle", "jusqu'à")
URL_PERMISES = {"http://www.w3.org/2000/svg"}        # espace de noms SVG, jamais telecharge
CHROMES = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
           r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
           "google-chrome", "chromium", "chromium-browser"]

OK = True


def v(libelle, cond, detail=""):
    global OK
    print("%s | %-60s %s" % ("OK   " if cond else "ECHEC", libelle, detail))
    if not cond:
        OK = False
    return cond


def canon(x):
    """Nombres normalises (146.0 == 146), cles triees : la forme commune."""
    if isinstance(x, float) and x.is_integer():
        return int(x)
    if isinstance(x, dict):
        return {k: canon(x[k]) for k in sorted(x)}
    if isinstance(x, list):
        return [canon(e) for e in x]
    return x


def egal(a, b):
    return json.dumps(canon(a), ensure_ascii=False, sort_keys=True) == \
           json.dumps(canon(b), ensure_ascii=False, sort_keys=True)


def jours_depuis(debut, n):
    d0 = dt.date.fromisoformat(debut)
    return [(d0 + dt.timedelta(days=k)).isoformat() for k in range(n)]


# =================================================== les cas, communs aux deux
def aleatoire(graine, n):
    """Serie de pluie fabriquee, reproductible : zeros, petites pluies, forts
    cumuls et jours sans donnee, sans dependre d'aucune bibliotheque."""
    x, serie = graine, []
    valeurs = [None, 0.0, 0.0, 0.0, 0.4, 1.0, 1.5, 3.2, 12.0, 29.9, 30.0, 30.5, 45.5, 72.4, 146.0, 212.5]
    for _ in range(n):
        x = (1103515245 * x + 12345) % 2147483648
        serie.append(valeurs[(x >> 16) % len(valeurs)])
    return serie


def construire_cas():
    phrases = []
    for k, d in enumerate(DEPTS):
        a = ["2026-01-01", "2026-09-30", "2026-10-01", "2026-02-28", "2026-12-31"][k % 5]
        mm = [30.0, 72.4, 146.0, 212.5, 99.5, 0.5][k % 6]
        phrases.append({"r": {"serie": "A", "cite_date": a, "cite_mm": mm}, "en": LIBELLES[d["code"]]})
        b = [("2026-02-06", "2026-03-07"), ("2025-12-15", "2026-01-13"), ("2026-09-02", "2026-10-01")][k % 3]
        phrases.append({"r": {"serie": "B", "debut_fenetre": b[0], "episode": b[1], "jours_pluie": 15 + k % 9},
                        "en": LIBELLES[d["code"]]})

    series = [{"p": [None, 35.0, 10.0], "dates": jours_depuis("2026-01-01", 3)}]
    for p in ([2.0] * 14 + [0.0] * 15 + [None], [2.0] * 14 + [0.0] * 15 + [1.0],
              [2.0] * 15 + [0.0] * 14 + [None], aleatoire(7, 160), aleatoire(2026, 160)):
        series.append({"p": p, "dates": jours_depuis("2026-01-01", len(p))})

    d10 = jours_depuis("2026-09-28", 10)
    cites = [{"p": [40.0, 80.0, 50.0, 0.0], "dates": d10[:4], "i": 0, "libre": None},
             {"p": [30.0 + k for k in range(8)], "dates": d10[:8], "i": 0, "libre": None},
             {"p": [40.0, None, 90.0], "dates": d10[:3], "i": 0, "libre": None},
             {"p": [90.0, 40.0], "dates": d10[:2], "i": 1, "libre": d10[1]},
             {"p": [90.0, 40.0], "dates": d10[:2], "i": 1, "libre": None},
             {"p": [50.0, 50.0], "dates": d10[:2], "i": 0, "libre": None}]
    for s in series[-2:]:
        for i, v_ in enumerate(s["p"]):
            if v_ is not None and v_ >= 30:
                cites.append({"p": s["p"], "dates": s["dates"], "i": i, "libre": None})
                cites.append({"p": s["p"], "dates": s["dates"], "i": i, "libre": s["dates"][max(0, i - 2)]})

    # Bascule : le premier episode tombe avant, le second apres. L'abandon ne
    # doit armer aucun verrou : le second part normalement, des deux cotes.
    p = [0.0] * 60
    p[10], p[20] = 50.0, 40.0
    dts = jours_depuis("2026-09-01", 60)
    dept = {"code": "99", "nom": "Essai", "region": "Essai"}
    traiter = [{"dept": dept, "p": p, "dates": dts, "aujourdhui": "2026-10-01",
                "etat": {"sequences": {}, "bascule": "2026-09-20"}},
               {"dept": dept, "p": p, "dates": dts, "aujourdhui": "2026-10-01",
                "etat": {"sequences": {}, "bascule": None}}]

    sequences = {
        "34|2026-09-30|A": {"etape": "mail1_envoye", "mail1_envoye_le": "2026-10-07"},
        "30|2026-09-30|A": {"etape": "mail1_monte", "mail1_monte_le": "2026-10-07"},
        "23|2026-09-30|A": {"etape": "mail1_monte", "mail1_monte_le": "2026-09-25"},
        "87|2026-09-30|A": {"etape": "mail2_monte", "mail1_envoye_le": "2026-10-07"},
        "14|2026-09-28|A": {"etape": "mail2_envoye", "mail1_envoye_le": "2026-10-05",
                            "mail2_envoye_le": "2026-10-19"},
        "73|2026-09-08|A": {"etape": "abandonne"},
    }
    scenarios = [
        {"nom": "au 06/10/2026, sans sequence", "pluie": "reference", "aujourdhui": "2026-10-06",
         "etat": {"sequences": {}, "bascule": None}},
        {"nom": "au 20/10/2026, sequences dans tous les etats et bascule au 10/10",
         "pluie": "reference", "aujourdhui": "2026-10-20",
         "etat": {"sequences": sequences, "bascule": "2026-10-10"}},
    ]
    pluies = {"reference": REFERENCE}
    if DU_JOUR:
        scenarios.append({"nom": "pluie.json du jour, au %s" % dt.date.today().isoformat(), "pluie": "jour",
                          "aujourdhui": dt.date.today().isoformat(), "etat": {"sequences": {}, "bascule": None}})
        pluies["jour"] = DU_JOUR

    return {
        "phrases": phrases,
        "arrondis": [0.0, 0.04, 0.4, 0.5, 1.5, 2.5, 29.5, 29.94, 30.0, 72.4, 99.5, 146.0, 212.5, 485.0],
        "jours": jours_depuis("2026-01-01", 365),
        "mentions": ["2026-10-06T06:23:06Z", "2026-10-01T06:00:00Z", "2026-03-29T00:59:59Z",
                     "2026-03-29T01:00:00Z", "2026-06-30T22:30:00Z", "2026-10-24T22:30:00Z",
                     "2026-10-25T00:59:59Z", "2026-10-25T01:00:00Z", "2026-10-25T23:30:00Z",
                     "2026-12-31T23:30:00Z", "2027-03-28T00:30:00Z", "2027-03-28T01:30:00Z", None],
        "periodes": list(PERIODES_SIMULATION),
        "series": series, "cites": cites, "traiter": traiter,
        "periode": list(PERIODE), "scenarios": scenarios, "pluies": pluies,
        "depts": DEPTS, "libelles": LIBELLES,
    }


# ========================================================== le cote JavaScript
EXECUTER_JS = r"""
function executer(D, cas) {
  const res = {};
  res.phrases = cas.phrases.map(x => D.blocMeteo(x.r, x.en));
  res.arrondis = cas.arrondis.map(x => D.mm(x));
  res.jours = cas.jours.map(s => D.jourLong(s));
  res.mentions = cas.mentions.map(s => D.mention(s));
  res.periodes = cas.periodes.map(f => D.periodeSimulation(f));
  res.series = cas.series.map(s => D.declencheurs(s.p, s.dates));
  res.cites = cas.cites.map(c => D.jourCite(c.p, c.dates, c.i, c.libre));
  res.traiter = cas.traiter.map(c => D.traiter(c.dept, c.p, c.dates, c.etat, c.aujourdhui));
  const ref = cas.pluies.reference, n = ref.stations[Object.keys(ref.stations)[0]].rr.length;
  const dates = Array.from({length: n}, (_, k) => D.plusJours(ref.debut, k));
  const i0 = dates.indexOf(cas.periode[0]), i1 = dates.indexOf(cas.periode[1]);
  res.declencheurs = {}; res.simulation = {};
  for (const code of Object.keys(ref.stations)) {
    const p = ref.stations[code].rr;
    res.declencheurs[code] = D.declencheurs(p, dates).map(t => t.serie === "A"
      ? [t.i, "A", t.pic24_mm].concat(D.jourCite(p, dates, t.i, null))
      : [t.i, "B", t.jours_pluie, t.debut_fenetre]);
    res.simulation[code] = D.simuler(p, dates, i0, i1);
  }
  res.scenarios = cas.scenarios.map(sc => {
    const pl = cas.pluies[sc.pluie], m = pl.stations[Object.keys(pl.stations)[0]].rr.length;
    const f = D.fenetre(pl.debut, m, sc.aujourdhui), dts = f.dates.slice(f.i0, f.i1 + 1);
    const attendu = D.attendu(sc.aujourdhui), faits = [], erreurs = [];
    for (const d of cas.depts) {
      const s = pl.stations[d.code];
      if (!s) { erreurs.push(d.code); continue; }
      const p = s.rr.slice(f.i0, f.i1 + 1);
      if (attendu > dts[dts.length - 1] || p[dts.indexOf(attendu)] === null) erreurs.push(d.code);
      const mention = D.mention(s.publie_le);
      for (const x of D.traiter(d, p, dts, sc.etat, sc.aujourdhui)) {
        x.mention = mention;
        if (x.etape !== "bloque") x.bloc_meteo = D.blocMeteo(x, cas.libelles[x.code] || ("dans le " + x.dept));
        faits.push(x);
      }
    }
    return {debut: dts[0], fin: dts[dts.length - 1], attendu, faits, erreurs};
  });
  return res;
}
"""

NODE_JS = EXECUTER_JS + r"""
const fs = require("fs");
const D = require(process.argv[2]);
const cas = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
let sortie;
try { sortie = executer(D, cas); } catch (e) { sortie = {erreur: String((e && e.stack) || e)}; }
process.stdout.write(JSON.stringify(sortie));
"""


def trouver_chrome():
    for c in CHROMES:
        p = c if os.path.isabs(c) else shutil.which(c)
        if p and os.path.exists(p):
            return p
    return None


def executer_js(cas):
    """Fait tourner detection.js sur les cas. Rend (resultats, moteur JS)."""
    t = tempfile.mkdtemp(prefix="coherence-")
    try:
        node = shutil.which("node")
        if node:
            io.open(os.path.join(t, "runner.js"), "w", encoding="utf-8").write(NODE_JS)
            io.open(os.path.join(t, "cas.json"), "w", encoding="utf-8").write(json.dumps(cas, ensure_ascii=False))
            r = subprocess.run([node, os.path.join(t, "runner.js"), os.path.abspath(DETECTION),
                                os.path.join(t, "cas.json")], capture_output=True, text=True,
                               encoding="utf-8", timeout=300)
            if r.returncode != 0:
                return {"erreur": r.stderr.strip()[-600:]}, "Node"
            return json.loads(r.stdout), "Node"
        if os.environ.get("GITHUB_ACTIONS"):
            return None, None                 # sur GitHub : Node obligatoire
        chrome = trouver_chrome()
        if not chrome:
            return None, None
        source = io.open(DETECTION, encoding="utf-8").read()
        donnees = json.dumps(cas, ensure_ascii=False).replace("</", "<\\/")
        page = ('<!doctype html><html><head><meta charset="utf-8"></head><body><pre id="resultat"></pre>\n'
                '<script>' + source.replace("</script", "<\\/script") + '</script>\n'
                '<script type="application/json" id="cas">' + donnees + '</script>\n'
                '<script>' + EXECUTER_JS + '\nlet sortie;\ntry { sortie = executer(window.Detection, '
                'JSON.parse(document.getElementById("cas").textContent)); }\n'
                'catch (e) { sortie = {erreur: String((e && e.stack) || e)}; }\n'
                'document.getElementById("resultat").textContent = JSON.stringify(sortie);\n</script>'
                '</body></html>')
        chemin = os.path.join(t, "runner.html")
        io.open(chemin, "w", encoding="utf-8").write(page)
        r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-first-run",
                            "--no-default-browser-check", "--user-data-dir=" + os.path.join(t, "profil"),
                            "--dump-dom", Path(chemin).as_uri()],
                           capture_output=True, text=True, encoding="utf-8", timeout=300)
        m = re.search(r'<pre id="resultat">(.*?)</pre>', r.stdout, re.S)
        if not m:
            return {"erreur": "Chrome n'a rien rendu : " + (r.stderr or r.stdout)[-400:]}, "Chrome"
        return json.loads(html.unescape(m.group(1))), "Chrome sans fenetre"
    finally:
        shutil.rmtree(t, ignore_errors=True)


# ============================================================== le cote Python
def lancer_moteur(sc):
    """Le moteur tel que le workflow le lance, dans un dossier temporaire."""
    t = tempfile.mkdtemp(prefix="coherence-")
    try:
        etat = {"version": 2, "bascule": sc["etat"]["bascule"], "sequences": sc["etat"]["sequences"],
                "campagnes": {}}
        io.open(os.path.join(t, "etat.json"), "w", encoding="utf-8").write(json.dumps(etat))
        pluie = os.path.join(RACINE, "pluie-reference.json" if sc["pluie"] == "reference" else "pluie.json")
        env = dict(os.environ, VP_DATE=sc["aujourdhui"], VP_PLUIE=pluie, VP_ETAT=os.path.join(t, "etat.json"),
                   VP_EXIGE_ETAT="1", VP_DEPTS=os.path.join(RACINE, "depts.json"),
                   VP_LIBELLES=os.path.join(RACINE, "libelles-departements.json"), PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, MOTEUR], capture_output=True, text=True, encoding="utf-8", env=env)
        if r.returncode != 0:
            return None, r.stderr.strip()[-300:]
        out = json.loads(r.stdout)
        faits = [f for k, l in out.items() if isinstance(l, list) for f in l if isinstance(f, dict) and "cle" in f]
        return {"debut": out["donnees"]["debut"], "fin": out["donnees"]["fin"], "attendu": out["donnees"]["attendu"],
                "faits": faits, "erreurs": [e["depts"][0] for e in out["erreurs"]]}, ""
    finally:
        shutil.rmtree(t, ignore_errors=True)


def cote_python(cas):
    res = {"phrases": [M.bloc_meteo(x["r"], x["en"]) for x in cas["phrases"]],
           "arrondis": [M._mm(x) for x in cas["arrondis"]],
           "jours": [M.jour_long(s) for s in cas["jours"]],
           "mentions": [M.mention(s) for s in cas["mentions"]],
           "series": [], "cites": [], "traiter": []}
    for s in cas["series"]:
        res["series"].append([dict(d, i=i, serie=sr) for i, sr, d in M.declencheurs(s["p"], s["dates"])])
    for c in cas["cites"]:
        libre = dt.date.fromisoformat(c["libre"]) if c["libre"] else None
        res["cites"].append(list(M.jour_cite(c["p"], c["dates"], c["i"], libre)))
    for c in cas["traiter"]:
        M.SEQ, M.AUJOURDHUI = c["etat"]["sequences"], dt.date.fromisoformat(c["aujourdhui"])
        M.BASCULE = dt.date.fromisoformat(c["etat"]["bascule"]) if c["etat"]["bascule"] else None
        res["traiter"].append(M.traiter(c["dept"], c["p"], c["dates"]))
    ref = cas["pluies"]["reference"]
    dates = jours_depuis(ref["debut"], len(next(iter(ref["stations"].values()))["rr"]))
    i0, i1 = dates.index(cas["periode"][0]), dates.index(cas["periode"][1])
    res["declencheurs"], res["simulation"] = {}, {}
    for code, s in ref["stations"].items():
        p = s["rr"]
        res["declencheurs"][code] = [
            [i, "A", d["pic24_mm"]] + list(M.jour_cite(p, dates, i, None)) if sr == "A"
            else [i, "B", d["jours_pluie"], d["debut_fenetre"]] for i, sr, d in M.declencheurs(p, dates)]
        res["simulation"][code] = M.simuler(p, dates, i0, i1)
    res["scenarios"] = [lancer_moteur(sc) for sc in cas["scenarios"]]
    return res


# =================================================================== controle
def phrases_interdites(phrases):
    return [p for p in phrases if p and any(w in p.lower() for w in MOTS_INTERDITS)]


def page():
    print("")
    print("6. La page")
    src = io.open(PAGE, encoding="utf-8").read()
    # La page appelle detection.js?v=<empreinte>. Sans cela, un navigateur peut
    # garder l'ancien detection.js en cache avec la nouvelle page : constate le
    # 07/10/2026. L'empreinte doit changer avec le fichier.
    empreinte = hashlib.sha256(io.open(DETECTION, "rb").read().replace(b"\r\n", b"\n")).hexdigest()[:8]
    m = re.search(r'<script src="detection\.js\?v=([0-9a-f]{8})"></script>', src)
    v("la page charge detection.js, empreinte a jour", bool(m) and m.group(1) == empreinte,
      "?v=%s" % empreinte if m and m.group(1) == empreinte
      else "index.html doit appeler detection.js?v=%s (trouve : %s)" % (empreinte, m.group(1) if m else "rien"))
    refaits = [f for f in ("function declencheurs(", "function traiter(", "function jourCite(",
                           "function simuler(", "function periodeSimulation(", "function blocMeteo(")
               if f in src]
    v("la page ne refait pas le calcul elle-meme", not refaits, ", ".join(refaits))
    m = re.search(r"const DEPT_EN=(\{.*?\});", src)
    v("prepositions de la page = libelles-departements.json",
      bool(m) and json.loads(m.group(1)) == LIBELLES, "%d departements" % len(LIBELLES))
    page_depts = re.findall(r'\{code:"(\w+)",nom:"([^"]*)",pref:"[^"]*",lat:[-\d.]+,lon:[-\d.]+,region:"([^"]*)"\}', src)
    v("departements de la page = depts.json (code, nom, region)",
      [list(x) for x in page_depts] == [[d["code"], d["nom"], d["region"]] for d in DEPTS],
      "%d departements" % len(page_depts))
    urls = set(re.findall(r"https?://[^\s\"'<>)]+", src + io.open(DETECTION, encoding="utf-8").read()))
    chargements = re.findall(r"<link[^>]+href=[\"']https?:|<script[^>]+src=[\"']https?:|@import|"
                             r"url\(\s*[\"']?https?:|fetch\(\s*[\"']https?:", src)
    v("aucune ressource exterieure chargee par la page",
      not chargements and urls <= URL_PERMISES, ", ".join(sorted(urls - URL_PERMISES) + chargements))


def main():
    print("Coherence moteur.py <-> detection.js (la page). Aucun acces reseau.")
    cas = construire_cas()
    js, moteur_js = executer_js(cas)
    if js is None:
        if os.environ.get("GITHUB_ACTIONS"):
            v("Node est installe sur le runner", False, "obligatoire sur GitHub")
        else:
            print("ATTENTION | ni Node ni Chrome ici : la comparaison avec detection.js N'EST PAS FAITE.")
        page()
        print("")
        print("RESULTAT : " + ("comparaison non faite, page seule controlee" if OK else "AU MOINS UN ECART"))
        return 1 if (os.environ.get("GITHUB_ACTIONS") or not OK) else 0
    print("JavaScript execute par : %s" % moteur_js)
    if "erreur" in js:
        v("detection.js s'execute sans erreur", False, js["erreur"][:300])
        return 1
    py = cote_python(cas)

    print("")
    print("1. Redaction")
    ecarts = [i for i, (a, b) in enumerate(zip(py["phrases"], js["phrases"])) if a != b]
    v("%d phrases identiques (series A et B, 96 departements)" % len(py["phrases"]),
      not ecarts and len(js["phrases"]) == len(py["phrases"]),
      "" if not ecarts else "%r <> %r" % (py["phrases"][ecarts[0]], js["phrases"][ecarts[0]]))
    v("arrondis au millimetre identiques, la demie vers le haut", py["arrondis"] == js["arrondis"],
      " ".join("%s->%s" % (x, r) for x, r in zip(cas["arrondis"], js["arrondis"])))
    v("365 dates en toutes lettres identiques, « 1er » compris", py["jours"] == js["jours"], "")
    v("mentions datees identiques, aux changements d'heure", py["mentions"] == js["mentions"],
      "" if py["mentions"] == js["mentions"] else str([(a, b) for a, b in zip(py["mentions"], js["mentions"]) if a != b][:2]))
    attendu_p = {k: {"debut": a, "fin": b} for k, (a, b) in PERIODES_SIMULATION.items()}
    v("periode de la Simulation : douze mois complets",
      all(egal(r, attendu_p[f]) for f, r in zip(cas["periodes"], js["periodes"])),
      "donnees au 04/10/2026 -> %s au %s" % (js["periodes"][0]["debut"], js["periodes"][0]["fin"]))

    print("")
    print("2. Calcul, cas fabriques")
    v("declencheurs identiques, jours sans donnee compris (%d series)" % len(cas["series"]),
      egal(py["series"], js["series"]), "")
    v("jours cites identiques (%d cas)" % len(cas["cites"]), egal(py["cites"], js["cites"]), "")
    v("verrou et bascule identiques", egal(py["traiter"], js["traiter"]), "")
    e_bascule = [f["etape"] for f in js["traiter"][0]]
    e_sans = [f["etape"] for f in js["traiter"][1]]
    v("l'abandon a la bascule n'arme aucun verrou", e_bascule == ["abandonne", "a_monter"], " / ".join(e_bascule))
    v("sans bascule, le verrou bloque le second episode", e_sans == ["a_monter", "bloque"], " / ".join(e_sans))

    print("")
    print("3. pluie-reference.json")
    ecarts = [c for c in py["declencheurs"] if not egal(py["declencheurs"][c], js["declencheurs"][c])]
    n_decl = sum(len(x) for x in js["declencheurs"].values())
    v("declencheurs et jours cites identiques, 96 departements", not ecarts and len(js["declencheurs"]) == 96,
      "%d declencheurs" % n_decl if not ecarts else "ecart : " + ", ".join(ecarts[:6]))
    ecarts = [c for c in py["simulation"] if not egal(py["simulation"][c], js["simulation"][c])]
    total_js = sum(len(x) for x in js["simulation"].values())
    total_py = sum(len(x) for x in py["simulation"].values())
    v("simulation identique, sequence par sequence", not ecarts, ", ".join(ecarts[:6]))
    v("236 sequences, 472 campagnes, des deux cotes", total_js == total_py == 236,
      "page %d, moteur %d campagnes" % (2 * total_js, 2 * total_py))
    # Compare departement par departement : JavaScript range les cles d'objet
    # « 10 » a « 95 » avant « 01 » et « 2A », l'ordre de lecture differe.
    ref = {c: [(x["episode"], x["serie"]) for x in l] for c, l in SEQUENCES_REFERENCE["par_departement"].items()}
    v("conforme a sequences-reference.json, departement par departement",
      {c: [(x["episode"], x["serie"]) for x in l] for c, l in js["simulation"].items()} == ref, "")

    print("")
    print("4. et 5. Le moteur lance comme par le workflow, contre la page")
    for sc, (p, err), j in zip(cas["scenarios"], py["scenarios"], js["scenarios"]):
        if p is None:
            v(sc["nom"] + " : le moteur tourne", False, err)
            continue
        cles_p = sorted(json.dumps(canon(f), ensure_ascii=False, sort_keys=True) for f in p["faits"])
        cles_j = sorted(json.dumps(canon(f), ensure_ascii=False, sort_keys=True) for f in j["faits"])
        seul_p = [x for x in cles_p if x not in cles_j]
        seul_j = [x for x in cles_j if x not in cles_p]
        etapes = {}
        for f in j["faits"]:
            etapes[f["etape"]] = etapes.get(f["etape"], 0) + 1
        v(sc["nom"], cles_p == cles_j and (p["debut"], p["fin"], p["attendu"]) == (j["debut"], j["fin"], j["attendu"])
          and p["erreurs"] == j["erreurs"],
          "%d lignes identiques, %s ; %d dept. en erreur" % (len(cles_j), ", ".join(
              "%s %d" % kv for kv in sorted(etapes.items())), len(j["erreurs"]))
          if cles_p == cles_j else "moteur seul : %s | page seule : %s" % (seul_p[:1], seul_j[:1]))
        if sc["nom"].startswith("au 06/10"):
            for code, phrase in (("34", "Le 30 septembre, 146 mm de pluie sont tombés en 24 heures dans l'Hérault."),
                                 ("30", "Le 30 septembre, 72 mm de pluie sont tombés en 24 heures dans le Gard.")):
                f = [x for x in j["faits"] if x["code"] == code and x["episode"] == "2026-09-30"]
                v("  phrase de la page, %s" % LIBELLES[code], len(f) == 1 and f[0].get("bloc_meteo") == phrase,
                  f[0].get("bloc_meteo") if f else "absente")
    if not DU_JOUR:
        print("        pluie.json absent : pas de comparaison sur les donnees du jour")

    toutes = js["phrases"] + [f.get("bloc_meteo") for sc in js["scenarios"] for f in sc["faits"]] \
        + py["phrases"] + [f.get("bloc_meteo") for p, _ in py["scenarios"] if p for f in p["faits"]]
    v("aucune phrase avec orage, averses, grele ou jusqu'a", not phrases_interdites(toutes),
      "%d phrases" % len([x for x in toutes if x]))

    page()
    print("")
    print("RESULTAT : " + ("moteur.py et la page calculent la meme chose" if OK
                           else "AU MOINS UN ECART — ne pas livrer"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
