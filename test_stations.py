#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Controle de stations.json, la liste figee des 96 stations Meteo-France.

Une station par departement : la plus proche de la prefecture, DANS le
departement, qui mesure la pluie. La liste n'est jamais recalculee ; la
modifier est un commit relu, et ce controle doit alors repasser.

Ce que le controle exige :
  - 96 stations, une et une seule par departement de depts.json
  - un numero Meteo-France de 8 chiffres, propre a une seule station
  - une station situee dans son departement : les deux premiers chiffres du
    numero sur le continent, le numero de commune en Corse
  - une distance a la prefecture recalculee sous 15 km, egale a celle inscrite
  - une altitude sous 1 000 m
  - un remplacement documente : numero, nom et motif de la station remplacee
  - aucune adresse email : le depot est public

Ses attendus sont ecrits en dur, et c'est voulu : un controle qui importe les
references qu'il verifie ne verifie plus rien.

Aucun acces reseau. Sortie : code 0 si tout passe, 1 sinon.

Usage :
    python test_stations.py [stations.json] [depts.json]
"""
import io, json, math, os, re, sys

sys.stdout.reconfigure(encoding="utf-8")

RACINE = os.path.dirname(os.path.abspath(__file__))
STATIONS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RACINE, "stations.json")
DEPTS = sys.argv[2] if len(sys.argv) > 2 else os.path.join(RACINE, "depts.json")

NB_DEPTS = 96
MAX_KM = 15.0
MAX_ALT = 1000
ECART_KM = 0.06          # la distance inscrite est arrondie au dixieme
CHAMPS = {"code", "num", "nom", "lat", "lon", "alt", "km", "retenue_le", "remplace"}
CHAMPS_REMPLACE = {"num", "nom", "motif"}

# Meteo-France publie un seul fichier pour la Corse, et numerote ses stations
# « 20 » + numero de commune d'avant la scission de 1976. Seul ce numero dit si
# une station est en Corse-du-Sud ou en Haute-Corse. Liste officielle des
# communes, relevee sur geo.api.gouv.fr le 06/10/2026 : 124 en 2A, 236 en 2B,
# aucun numero commun aux deux.
COMMUNES = {
    "2A": set("""
001 004 006 008 011 014 017 018 019 021 022 024 026 027 028 031 032 035
038 040 041 048 056 060 061 062 064 065 066 070 071 085 089 090 091 092
094 098 099 100 103 104 108 114 115 117 118 119 127 128 129 130 131 132
133 139 141 142 144 146 154 158 160 163 174 181 186 189 191 196 197 198
200 203 204 209 211 212 215 228 232 240 247 249 253 254 258 259 262 266
268 269 270 271 272 276 278 279 282 284 285 288 295 300 308 310 312 322
323 324 326 330 331 336 345 348 349 351 357 358 359 360 362 363
""".split()),
    "2B": set("""
002 003 005 007 009 010 012 013 015 016 020 023 025 029 030 033 034 036
037 039 042 043 045 046 047 049 050 051 052 053 054 055 057 058 059 063
067 068 069 072 073 074 075 077 078 079 080 081 082 083 084 086 087 088
093 095 096 097 101 102 105 106 107 109 110 111 112 113 116 120 121 122
123 124 125 126 134 135 136 137 138 140 143 145 147 148 149 150 152 153
155 156 157 159 161 162 164 165 166 167 168 169 170 171 172 173 175 176
177 178 179 180 182 183 184 185 187 188 190 192 193 194 195 199 201 202
205 206 207 208 210 213 214 216 217 218 219 220 221 222 223 224 225 226
227 229 230 231 233 234 235 236 238 239 241 242 243 244 245 246 248 250
251 252 255 256 257 260 261 263 264 265 267 273 274 275 277 280 281 283
286 287 289 290 291 292 293 296 297 298 299 301 302 303 304 305 306 307
309 311 313 314 315 316 317 318 319 320 321 327 328 329 332 333 334 335
337 338 339 340 341 342 343 344 346 347 350 352 353 354 355 356 361 364
365 366
""".split()),
}

NUMERO = re.compile(r"^\d{8}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ADRESSE = re.compile(r"@[^\s\"]*\.")

OK = True


def v(libelle, cond, detail=""):
    global OK
    print("%s | %-52s %s" % ("OK   " if cond else "ECHEC", libelle, detail))
    if not cond:
        OK = False
    return cond


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def dans_le_departement(s):
    """La station est-elle dans son departement ?"""
    num, code = s["num"], s["code"]
    if code in COMMUNES:
        return num[:2] == "20" and num[2:5] in COMMUNES[code]
    return num[:2] == code


def liste(xs, n=6):
    xs = list(xs)
    return ", ".join(xs[:n]) + (" ..." if len(xs) > n else "")


def main():
    print("Controle de la liste figee des stations Meteo-France. Aucun acces reseau.")
    print("")
    brut = io.open(STATIONS, encoding="utf-8").read()
    doc = json.loads(brut)
    depts = {d["code"]: d for d in json.load(io.open(DEPTS, encoding="utf-8"))}
    st = doc.get("stations") or []

    # --- 1. Une station par departement -----------------------------------
    codes = [s.get("code") for s in st]
    v("%d departements dans depts.json" % NB_DEPTS, len(depts) == NB_DEPTS, "%d trouve(s)" % len(depts))
    v("%d stations" % NB_DEPTS, len(st) == NB_DEPTS, "%d trouvee(s)" % len(st))
    v("une station par departement, aucun en double",
      len(set(codes)) == len(codes), liste(c for c in set(codes) if codes.count(c) > 1))
    v("aucun departement sans station", not set(depts) - set(codes), liste(sorted(set(depts) - set(codes))))
    v("aucune station hors des 96 departements", not set(codes) - set(depts),
      liste(sorted(str(c) for c in set(codes) - set(depts))))
    v("stations dans l'ordre de depts.json",
      codes == [c for c in depts if c in set(codes)], "")

    # --- 2. Forme de chaque entree ----------------------------------------
    mal = [str(s.get("code")) for s in st if set(s) != CHAMPS]
    v("chaque entree porte exactement les champs prevus", not mal, liste(mal))
    mal = [str(s.get("code")) for s in st if not NUMERO.match(str(s.get("num")))]
    v("numero Meteo-France de 8 chiffres", not mal, liste(mal))
    nums = [s.get("num") for s in st]
    v("aucune station retenue pour deux departements", len(set(nums)) == len(nums),
      liste(n for n in set(nums) if nums.count(n) > 1))
    mal = [str(s.get("code")) for s in st if not str(s.get("nom") or "").strip()]
    v("chaque station a un nom", not mal, liste(mal))
    mal = [str(s.get("code")) for s in st if not DATE.match(str(s.get("retenue_le")))]
    v("date de retenue au format AAAA-MM-JJ", not mal, liste(mal))

    # --- 3. Dans le departement --------------------------------------------
    hors = [s["code"] for s in st if s.get("code") in depts and NUMERO.match(str(s.get("num")))
            and not dans_le_departement(s)]
    v("chaque station est dans son departement", not hors,
      liste("%s:%s" % (c, [s["num"] for s in st if s["code"] == c][0]) for c in hors))
    corse = [s for s in st if s.get("code") in COMMUNES]
    v("Corse : deux stations, classees par numero de commune",
      len(corse) == 2 and all(dans_le_departement(s) for s in corse),
      ", ".join("%s %s commune %s" % (s["code"], s["num"], s["num"][2:5]) for s in corse))

    # --- 4. Distance et altitude -------------------------------------------
    calc = {s["code"]: km((depts[s["code"]]["lat"], depts[s["code"]]["lon"]), (s["lat"], s["lon"]))
            for s in st if s.get("code") in depts}
    loin = [c for c, d in calc.items() if d > MAX_KM]
    v("toutes a moins de %d km de la prefecture" % MAX_KM, not loin,
      liste("%s:%.1f km" % (c, calc[c]) for c in loin))
    faux = [s["code"] for s in st if s.get("code") in calc and abs(calc[s["code"]] - s["km"]) > ECART_KM]
    v("distance inscrite egale a la distance recalculee", not faux,
      liste("%s:%s inscrit, %.2f recalcule" % (c, [s["km"] for s in st if s["code"] == c][0], calc[c])
            for c in faux))
    haut = [s["code"] for s in st if not isinstance(s.get("alt"), int) or s["alt"] >= MAX_ALT]
    v("toutes sous %d m d'altitude" % MAX_ALT, not haut, liste(haut))
    if calc:
        loin_c = max(calc, key=calc.get)
        print("        distance maximale : %.1f km (%s), altitude maximale : %d m (%s)"
              % (calc[loin_c], loin_c, max(s["alt"] for s in st),
                 max(st, key=lambda s: s["alt"])["code"]))

    # --- 5. Remplacements --------------------------------------------------
    rempl = [s for s in st if s.get("remplace") is not None]
    mal = [s["code"] for s in rempl
           if not isinstance(s["remplace"], dict) or set(s["remplace"]) != CHAMPS_REMPLACE
           or not NUMERO.match(str(s["remplace"].get("num"))) or s["remplace"]["num"] == s["num"]
           or not str(s["remplace"].get("motif") or "").strip()]
    v("remplacements documentes : numero, nom, motif", not mal, liste(mal))
    for s in rempl:
        print("        %s : %s remplace %s %s (%s)" % (s["code"], s["nom"], s["remplace"]["num"],
                                                   s["remplace"]["nom"], s["remplace"]["motif"]))

    # --- 6. Depot public ---------------------------------------------------
    v("aucune adresse email dans le fichier", not ADRESSE.search(brut), "")

    print("")
    print("RESULTAT : " + ("la liste des stations est conforme"
                           if OK else "AU MOINS UN ECART — ne pas livrer"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
