/* Détection de la veille pluviométrique Ax'eau, partagée par la page et les tests.
 *
 * Réplique exacte de moteur.py : mêmes seuils, même fenêtre, même verrou, même
 * jour cité, même arrondi, même phrase. La page charge ce fichier ; les tests le
 * font tourner sous Node et comparent son résultat à celui du moteur, à l'unité.
 * TOUTE MODIFICATION DE L'UN DOIT ÊTRE REPORTÉE SUR L'AUTRE.
 *
 * Des fonctions pures : ni page, ni réseau. Les dates sont des chaînes
 * AAAA-MM-JJ, calculées en UTC : ni fuseau, ni heure d'été.
 *
 * Un jour sans donnée (null) ne déclenche rien et ne compte pas comme jour de
 * pluie. Jamais 0 : un jour sans donnée est une erreur, pas un jour sec.
 */
(function (racine) {
  "use strict";

  const FENETRE = 30, OFFSET_1 = 7, ECART_2 = 14, SILENCE = 30, EXPIRATION = 21;
  const PROFONDEUR = 92;
  // Météo-France publie la pluie du jour J le matin du jour J+2 : au mail 1,
  // à J+7, les journées connues vont jusqu'à J+5.
  const DELAI_PUBLICATION = 2;
  const CONNU_AU_MAIL1 = OFFSET_1 - DELAI_PUBLICATION;
  const REGLAGES = Object.freeze({pic: 30, seuilJour: 1, nbJours: 15});
  const MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                "août", "septembre", "octobre", "novembre", "décembre"];
  const MENTION = "Données pluviométriques : Météo-France, mise à jour du ";

  // ------------------------------------------------------------- dates
  function versUTC(s) {
    const [a, m, j] = s.split("-").map(Number);
    return Date.UTC(a, m - 1, j);
  }
  function plusJours(s, n) {
    return new Date(versUTC(s) + n * 864e5).toISOString().slice(0, 10);
  }
  function ecartJours(a, b) {            // b - a, en jours
    return Math.round((versUTC(b) - versUTC(a)) / 864e5);
  }

  // ---------------------------------------------------------- rédaction
  // Arrondi au millimètre, la demie vers le haut : 146 -> 146, 72,4 -> 72,
  // 212,5 -> 213. moteur.py fait floor(v + 0,5), qui donne la même chose.
  function mm(v) {
    return String(Math.floor(v + 0.5));
  }
  // « 30 septembre », « 1er octobre ». Seul le 1er prend « er ».
  function jourLong(s) {
    const [, m, j] = s.split("-").map(Number);
    return (j === 1 ? "1er" : String(j)) + " " + MOIS[m - 1];
  }
  // Mention de source, datée à Paris de la publication du fichier Météo-France
  // qui a servi. moteur.py applique la règle européenne de l'heure d'été ;
  // Europe/Paris applique la même.
  function mention(publieLe) {
    if (!publieLe) return null;
    const p = {};
    new Intl.DateTimeFormat("fr-FR", {timeZone: "Europe/Paris", year: "numeric", month: "numeric", day: "numeric"})
      .formatToParts(new Date(publieLe)).forEach(x => { p[x.type] = x.value; });
    const j = Number(p.day);
    return MENTION + (j === 1 ? "1er" : String(j)) + " " + MOIS[Number(p.month) - 1] + " " + p.year;
  }
  // Phrase exacte injectée dans %%BLOC_METEO%% du gabarit.
  function blocMeteo(r, deptEn) {
    if (r.serie === "B")
      return `Entre le ${jourLong(r.debut_fenetre)} et le ${jourLong(r.episode)}, ` +
             `${r.jours_pluie} jours de pluie ont été relevés ${deptEn}.`;
    return `Le ${jourLong(r.cite_date)}, ${mm(r.cite_mm)} mm de pluie ` +
           `sont tombés en 24 heures ${deptEn}.`;
  }

  // ---------------------------------------------------------- détection
  function declencheurs(p, dates, rg) {
    rg = rg || REGLAGES;
    const out = [];
    for (let i = 0; i < p.length; i++)
      if (p[i] !== null && p[i] >= rg.pic)
        out.push({i, serie: "A", pic24_mm: Math.round(p[i] * 10) / 10, pic_date: dates[i]});
    for (let i = 0; i < p.length; i++) {
      if (p[i] === null) continue;
      const deb = Math.max(0, i - (FENETRE - 1));
      let n = 0;
      for (let k = deb; k <= i; k++) if (p[k] !== null && p[k] >= rg.seuilJour) n++;
      if (n >= rg.nbJours)
        out.push({i, serie: "B", jours_pluie: n, seuil_jour_mm: rg.seuilJour, debut_fenetre: dates[deb]});
    }
    out.sort((a, b) => a.i - b.i || (a.serie < b.serie ? -1 : a.serie > b.serie ? 1 : 0));
    return out;
  }

  // Le jour que cite le mail : le plus fort des jours consécutifs à rg.pic mm
  // ou plus autour du déclenchement i, sans remonter dans le verrou précédent
  // (libre = premier jour libre, ou null), connu au mail 1. Un jour sans
  // donnée interrompt l'épisode. À égalité, le plus tôt. Rend [date, valeur].
  function jourCite(p, dates, i, libre, rg) {
    rg = rg || REGLAGES;
    const fort = k => p[k] !== null && p[k] >= rg.pic;
    let k0 = i;
    while (k0 > 0 && fort(k0 - 1) && (libre === null || dates[k0 - 1] >= libre)) k0--;
    let k1 = i;
    while (k1 + 1 < p.length && k1 + 1 <= i + CONNU_AU_MAIL1 && fort(k1 + 1)) k1++;
    let best = k0;
    for (let k = k0 + 1; k <= k1; k++) if (p[k] > p[best]) best = k;
    return [dates[best], p[best]];
  }

  // Déroule la chronologie d'un département. etat = {sequences, bascule}.
  function traiter(dept, p, dates, etat, aujourdhui, rg) {
    rg = rg || REGLAGES;
    const seq = (etat && etat.sequences) || {}, bascule = (etat && etat.bascule) || null;
    const jour = d => ecartJours(aujourdhui, d);
    const faits = [];
    let libre = null;                    // date avant laquelle aucune nouvelle séquence
    for (const t of declencheurs(p, dates, rg)) {
      const episode = dates[t.i];
      const cle = dept.code + "|" + episode + "|" + t.serie;
      const connue = seq[cle];
      const detail = t.serie === "A"
        ? {pic24_mm: t.pic24_mm, pic_date: t.pic_date}
        : {jours_pluie: t.jours_pluie, seuil_jour_mm: t.seuil_jour_mm, debut_fenetre: t.debut_fenetre};
      if (t.serie === "A") {
        const c = jourCite(p, dates, t.i, libre, rg);
        detail.cite_date = c[0]; detail.cite_mm = c[1];
      }

      if (!connue && libre !== null && episode < libre) {
        faits.push({code: dept.code, dept: dept.nom, region: dept.region, cle, etape: "bloque",
                    episode, serie: t.serie, libre_le: libre, ...detail});
        continue;
      }

      const m1 = plusJours(episode, OFFSET_1);
      const base = {code: dept.code, dept: dept.nom, region: dept.region, cle, serie: t.serie,
                    episode, mail1_prevu: m1, ...detail};

      if (!connue) {
        if (bascule && m1 < bascule) {
          faits.push({...base, etape: "abandonne", motif: "anterieur a la bascule du " + bascule});
          continue;                      // n'arme pas le verrou
        }
        if (jour(m1) < -EXPIRATION) { faits.push({...base, etape: "expire"}); continue; }
        faits.push({...base, etape: jour(m1) <= 0 ? "a_monter" : "a_venir", jours: jour(m1)});
        libre = plusJours(m1, ECART_2 + SILENCE);
        continue;
      }

      const e = connue.etape;
      for (const k in connue) if (k !== "etape") base[k] = connue[k];

      if (e === "abandonne") { faits.push({...base, etape: "abandonne"}); continue; }

      if (e === "mail1_monte") {
        const age = -jour(connue.mail1_monte_le);
        if (age > EXPIRATION) { faits.push({...base, etape: "expire_non_envoye", age_jours: age}); libre = null; }
        else { faits.push({...base, etape: "attente_envoi_mail1", age_jours: age}); libre = plusJours(m1, ECART_2 + SILENCE); }
        continue;
      }
      if (e === "mail1_envoye") {
        const m2 = plusJours(connue.mail1_envoye_le, ECART_2);
        faits.push({...base, etape: jour(m2) <= 0 ? "mail2_a_monter" : "mail2_a_venir",
                    mail2_prevu: m2, jours: jour(m2)});
        libre = plusJours(m2, SILENCE);
        continue;
      }
      if (e === "mail2_monte") {
        const m2 = plusJours(connue.mail1_envoye_le, ECART_2);
        faits.push({...base, etape: "attente_envoi_mail2", mail2_prevu: m2});
        libre = plusJours(m2, SILENCE);
        continue;
      }
      if (e === "mail2_envoye") {
        const fin = plusJours(connue.mail2_envoye_le, SILENCE);
        faits.push({...base, etape: jour(fin) < 0 ? "silence" : "termine", silence_jusquau: fin});
        libre = fin;
        continue;
      }
      faits.push({...base, etape: e || "inconnu"});
    }
    return faits;
  }

  // Ce que compte l'onglet Simulation : les séquences qu'auraient ouvertes les
  // déclencheurs, mails partis à l'heure. Démarrage à froid à l'indice depuis,
  // déclencheurs retenus jusqu'à l'indice jusquA inclus. Un département est
  // libre à l'épisode + 51 jours.
  function simuler(p, dates, depuis, jusquA, rg) {
    rg = rg || REGLAGES;
    depuis = depuis || 0;
    jusquA = (jusquA === undefined || jusquA === null) ? p.length - 1 : jusquA;
    const seqs = [];
    let libre = null;
    for (const t of declencheurs(p, dates, rg)) {
      if (t.i < depuis || t.i > jusquA) continue;
      const e = dates[t.i];
      if (libre !== null && e < libre) continue;
      const x = {episode: e, serie: t.serie};
      if (t.serie === "A") {
        x.pic24_mm = t.pic24_mm; x.pic_date = t.pic_date;
        const c = jourCite(p, dates, t.i, libre, rg);
        x.cite_date = c[0]; x.cite_mm = c[1];
      } else {
        x.jours_pluie = t.jours_pluie; x.seuil_jour_mm = t.seuil_jour_mm; x.debut_fenetre = t.debut_fenetre;
      }
      seqs.push(x);
      libre = plusJours(e, OFFSET_1 + ECART_2 + SILENCE);
    }
    return seqs;
  }

  // L'onglet Simulation porte sur douze mois complets : du 1er du mois, onze
  // mois avant le dernier mois entièrement publié, à la fin de ce mois-là.
  // Données jusqu'au 04/10/2026 -> du 01/10/2025 au 30/09/2026.
  function periodeSimulation(fin) {
    const [a, m, j] = fin.split("-").map(Number);
    const jours = (an, mois) => new Date(Date.UTC(an, mois, 0)).getUTCDate();
    let fa = a, fm = m;
    if (j !== jours(a, m)) { fm = m - 1; if (fm === 0) { fm = 12; fa = a - 1; } }
    let da = fa, dm = fm - 11;
    if (dm <= 0) { dm += 12; da -= 1; }
    const deux = x => String(x).padStart(2, "0");
    return {debut: da + "-" + deux(dm) + "-01", fin: fa + "-" + deux(fm) + "-" + deux(jours(fa, fm))};
  }

  // ---------------------------------------------------------- données
  // Toutes les dates de pluie.json, et la fenêtre de détection du moteur :
  // PROFONDEUR jours, jusqu'au dernier jour publié.
  function fenetre(debutDonnees, n, aujourdhui) {
    const dates = Array.from({length: n}, (_, k) => plusJours(debutDonnees, k));
    const debut = [plusJours(aujourdhui, -PROFONDEUR), dates[0]].sort()[1];
    const fin = [aujourdhui, dates[n - 1]].sort()[0];
    return {dates, i0: dates.indexOf(debut), i1: dates.indexOf(fin)};
  }
  // Le jour qui devrait être publié aujourd'hui.
  function attendu(aujourdhui) {
    return plusJours(aujourdhui, -DELAI_PUBLICATION);
  }

  const D = {FENETRE, OFFSET_1, ECART_2, SILENCE, EXPIRATION, PROFONDEUR, DELAI_PUBLICATION,
             CONNU_AU_MAIL1, REGLAGES, MOIS, plusJours, ecartJours, mm, jourLong, mention, blocMeteo,
             declencheurs, jourCite, traiter, simuler, periodeSimulation, fenetre, attendu};
  if (typeof module !== "undefined" && module.exports) module.exports = D;
  else racine.Detection = D;
})(typeof window !== "undefined" ? window : this);
