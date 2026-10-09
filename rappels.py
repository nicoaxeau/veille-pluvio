#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ecrit rappels.xml : le flux RSS des brouillons a envoyer.

Lu chaque matin par un flux Power Automate, avec le connecteur RSS standard :
c'est lui, et lui seul, qui envoie le mail de rappel, depuis l'Outlook de
Nicolas, a trois destinataires figes dans le flux. Ce depot ne sait toujours
rien envoyer : il publie une date et un lien.

Un element par campagne inscrite dans etat.json et pas encore envoyee
(sans envoye_le) :
  titre     « À envoyer le 21/10/2026 : mail 2 Hérault »
  lien      le brouillon dans Mailjet
  date      le jour ou le mail doit partir, a 6 h UTC : envoi_prevu, pose par
            le montage, deja reporte au jour ouvre suivant un samedi, un
            dimanche ou un ferie (decision du 09/10/2026). A defaut, pour les
            campagnes montees avant : mail 1 episode + 7 jours, mail 2 envoi
            du mail 1 + 14 jours

LE DEPOT EST PUBLIC : ni adresse, ni nom de liste, ni compteur. Un departement,
une date, un lien de brouillon (qui ne s'ouvre qu'avec le compte Mailjet).

Usage :
    python rappels.py [etat.json] [rappels.xml]
"""
import datetime as dt, email.utils, io, json, sys
from xml.sax.saxutils import escape

sys.stdout.reconfigure(encoding="utf-8")

OFFSET_1, ECART_2 = 7, 14
SITE = "https://nicoaxeau.github.io/veille-pluvio/"


def date_envoi(c, sequences):
    """Le jour ou ce mail doit partir, ou None si on ne sait pas le dire."""
    if c.get("envoi_prevu"):
        return dt.date.fromisoformat(c["envoi_prevu"])
    if c.get("etape") == "mail1" and c.get("episode"):
        return dt.date.fromisoformat(c["episode"]) + dt.timedelta(days=OFFSET_1)
    s = sequences.get(c.get("cle")) or {}
    if c.get("etape") == "mail2" and s.get("mail1_envoye_le"):
        return dt.date.fromisoformat(s["mail1_envoye_le"]) + dt.timedelta(days=ECART_2)
    return None


def elements(etat):
    seqs = etat.get("sequences") or {}
    out = []
    for bid, c in (etat.get("campagnes") or {}).items():
        if c.get("envoye_le"):
            continue
        d = date_envoi(c, seqs)
        if not d:
            continue
        mail = "mail 1" if c.get("etape") == "mail1" else "mail 2"
        out.append((d, "À envoyer le %s : %s %s" % (d.strftime("%d/%m/%Y"), mail, c.get("nom_dept") or c.get("dept")),
                    "https://app.mailjet.com/campaigns/draft/%s/edit" % bid, bid))
    return sorted(out)


def rss(etat, maintenant=None):
    maintenant = maintenant or dt.datetime.now(dt.timezone.utc)
    modele = ("  <item>\n    <title>%s</title>\n    <link>%s</link>\n"
              "    <guid isPermaLink=\"false\">brouillon-%s</guid>\n"
              "    <pubDate>%s</pubDate>\n    <description>%s</description>\n  </item>\n")
    items = ""
    for d, t, l, b in elements(etat):
        quand = email.utils.format_datetime(dt.datetime.combine(d, dt.time(6), dt.timezone.utc))
        texte = "Brouillon deja pret dans Mailjet. Il reste a cliquer sur Envoyer. Date : %s" % d.isoformat()
        items += modele % (escape(t), escape(l), escape(str(b)), quand, escape(texte))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0">\n<channel>\n'
            "  <title>Veille pluviometrique Ax'eau : brouillons a envoyer</title>\n"
            "  <link>%s</link>\n  <description>Un element par brouillon pret et pas encore envoye.</description>\n"
            "  <lastBuildDate>%s</lastBuildDate>\n%s</channel>\n</rss>\n"
            % (SITE, email.utils.format_datetime(maintenant), items))


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "etat.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "rappels.xml"
    etat = json.load(io.open(src, encoding="utf-8"))
    texte = rss(etat)
    if "@" in texte:
        print("ECHEC | rappels.xml contiendrait un « @ » : rien n'est ecrit")
        return 1
    io.open(dst, "w", encoding="utf-8", newline="\n").write(texte)
    for d, t, l, b in elements(etat):
        print("  %s  %s" % (t, l))
    print("%d rappel(s) dans %s" % (len(elements(etat)), dst))
    return 0


if __name__ == "__main__":
    sys.exit(main())
