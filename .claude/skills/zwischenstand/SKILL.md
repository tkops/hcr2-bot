---
name: zwischenstand
description: Zwischenstand eines noch laufenden Team-Matches auswerten - wer ist noch nicht gefahren, wer haengt hinter ihrem eigenen Score aus diesem Event, wen kann man loben. Nutzen, wenn ein Video eines laufenden Matches vorliegt (Countdown laeuft noch), egal wie formuliert ("/zwischenstand 810", "810-tmp ist hochgeladen", "Zwischenstand auswerten", "wer ist noch nicht gefahren", "wer kann sich noch steigern"). Schreibt nichts in die DB. Fuer den Endstand ist [[match-video]] zustaendig, das auch die Leseanleitung haelt.
---

# Zwischenstand auswerten

Nur ein Einstieg. Die Arbeit steht in
`.claude/skills/match-video/SKILL.md`, Abschnitt **„Modus Zwischenstand (die Uhr läuft
noch)"** — dort liegen Frames, Kaderzuordnung, Transliteration und der Ablauf.
Bewusst nicht kopiert: eine zweite Kopie der Leseanleitung driftet von der ersten weg.

Argument: die Match-ID (optional).

## Ablauf

1. **Skill [[match-video]] aufrufen** und dort dem Modus Zwischenstand folgen:
   Schritte 1–5 (Frames, Kader, Lesen, Zuordnen, Nicht-Gefahrene) unverändert,
   danach 6b (`interim.json` mit `time_left`), 7b (`video interim`), 8b (`--cleanup`).
2. Video heißt üblicherweise `<id>-tmp.mp4` → `--file` setzen.
   Gibt es die Match-Zeile noch nicht, `--season <n>` benutzen und danach `match add`
   vorschlagen — **ohne Ergebnisse**.

## Was hier gilt und nicht verhandelbar ist

- **Läuft im Videokopf kein Countdown, ist es der Endstand** — dann nicht dieser Weg,
  sondern der reguläre Ablauf in [[match-video]]. Umgekehrt gilt dasselbe: eine
  Zwischenlesung nie mit `video apply` schreiben. Sie macht aus „noch nicht gefahren"
  ein unentschuldigtes Fehlen, und in der Probezeit ist das ein Sofortfall in
  `stats broom`. `video apply` weist eine Lesung mit `time_left` deshalb auch ab.
- **Nichts wird geschrieben.** `video interim` liest nur.
- **Nicht als Vorwurf weitergeben**, solange die Uhr läuft: „noch nicht gefahren" ist
  eine Erinnerung, und eine Prozentzahl unter 100 kann auch heißen, dass sie gerade
  fährt.
