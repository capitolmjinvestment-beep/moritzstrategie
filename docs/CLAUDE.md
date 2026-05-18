# CLAUDE.md — Working Instructions for Claude Code

Diese Datei sind die Working-Instructions für Claude Code. Du wirst sie automatisch bei jedem Session-Start lesen.

## Wer du bist und was du baust

Du arbeitest mit Moritz an einem Algo-Trading-Bot:
- **Strategie:** Clean H4 Camarilla Reversal (Spec siehe `MASTERPLAN.md`)
- **Basis-Codebase:** MjCapital-Scalping (ursprünglich 1m-Scalper, wird auf 4h umgebaut)
- **Echtgeld-Ziel:** Live auf Bitget mit 1000 € Risikokapital, nach durchlaufenen Phasen 1-5
- **Aktueller Stand:** Plan steht. Phase 1 (Daten-Pipeline auf 4h) beginnt.

## Die wichtigsten Regeln

### 1. MASTERPLAN.md ist die Wahrheit

Bevor du Code schreibst, lies `MASTERPLAN.md`. Wenn etwas im Code dem Plan widerspricht: stoppe, frage Moritz, ob der Plan oder der Code falsch ist. Code-Plan-Drift ist der häufigste Weg, wie Trading-Bots Geld verlieren.

### 2. Phasen-Disziplin

Aktuelle Phase steht in `MASTERPLAN.md` Section 10. Implementiere **nur Files für die aktuelle Phase**. Keine vorgreifenden Implementierungen "weil es leicht ist". Phase-Gates sind keine Vorschläge.

### 3. Look-Ahead-Bias ist Todsünde

Strategien und Indikatoren dürfen NIE Daten aus der Zukunft sehen. Beispiele:
- Camarilla-Levels für Tag T dürfen NUR aus Daten von Tag T−1 berechnet werden
- Bei Bar T darf die Strategie nur Bars ≤ T sehen
- Beim Backtest: an Bar-Close fillen, nicht innerhalb der Bar
- Wenn du unsicher bist, ob Bias drin ist: **frag Moritz und füg einen TODO-Kommentar im Code ein**

### 4. Tests sind Pflicht, nicht optional

Jede Indikator-Klasse, jede Strategie-Methode bekommt Unit-Tests. Bei `pytest`-Fail wird nicht gemerged. Mindestens:
- Happy Path
- Edge Cases (leere Daten, NaN, Daten am Rand)
- Look-Ahead-Test (verifiziert, dass Indikator bei Bar T nur Daten ≤ T sieht)

### 5. Keine externe Library ohne Rückfrage

Repo nutzt: polars, pydantic, structlog, decimal. Wenn du eine neue Dependency willst (pandas, numpy, ta-lib, scipy, ...), **erst fragen**. Begründung: jede neue Dependency ist potenziell Angriffsfläche und Versionskonflikt-Risiko in Production.

### 6. Decimal überall

Preise, Quantities, Equity – alles `Decimal`, nie `float`. Float-Rundungen haben Trader bereits siebenstellige Beträge gekostet. Im bestehenden Code ist das so – halte es so.

### 7. Stil

- Type-Hints überall (`mypy` muss durchgehen, siehe `mypy.ini`)
- Ruff-clean (siehe `ruff.toml`)
- Docstrings auf Funktions- und Klassenebene
- Kommentare auf Deutsch oder Englisch ist beides ok, aber konsistent in einem File
- Keine TODO-Kommentare ohne Issue-Nummer oder Datum

### 8. Wenn du etwas nicht weißt, frag

Lieber 30 Sekunden Rückfrage als eine Stunde falsche Implementierung. Insbesondere bei:
- Strategie-Regel-Interpretation (was genau heißt "RSI war innerhalb der letzten 3 Bars unter 30"?)
- Exchange-API-Details (Bitget hat versteckte Quirks, lieber Bitget-Doku zitieren)
- Risk-Management-Entscheidungen

### 9. Was du NIE selbst entscheiden darfst

- Strategie-Parameter ändern (z.B. RSI-Schwelle von 30 auf 35)
- Stops oder Position-Sizes erhöhen
- Aus Phase 5 in Phase 6 wechseln
- Live-Trading aktivieren (API-Keys, etc.)
- Risk-Limits hochsetzen
- Indikatoren ohne Plan-Update hinzufügen

Bei all diesen Fragen: **Stoppe, frage Moritz.**

### 10. Commit-Disziplin

- Ein logischer Change = ein Commit
- Commit-Message: erster Satz beschreibt das *Was* (Imperativ, engl.: "Add Camarilla pivot indicator"), Body beschreibt das *Warum*
- Vor jedem Commit: `pytest tests/`, `ruff check`, `mypy src/scalping/`
- Beim Phasen-Wechsel: Git-Tag (`phase1-complete`, `phase2-complete`, ...)

## Format deiner Antworten

Wenn du Code schreibst:
1. **Kurz erklären**, was du machst und warum (2-4 Sätze)
2. **Code** schreiben
3. **Tests** schreiben (im selben Turn, nicht "machen wir später")
4. **Hinweisen**, was Moritz prüfen oder als nächstes tun soll

Wenn etwas unklar ist:
- Frage **gezielt** (Multiple Choice wenn möglich)
- Nicht "Was soll ich machen?" sondern "Soll RSI-Periode 14 oder 21 sein?"

Wenn du einen Fehler im Plan siehst:
- Sag es. Direkt. Auch wenn unbequem.
- "Im Plan steht X, das halte ich für problematisch weil Y. Vorschlag: Z."

## Was Moritz NICHT von dir braucht

- Generische Risk-Disclaimer ("Trading is risky"). Er weiß. Er hat 1000 € als Risikokapital deklariert.
- Ermutigungs-Phrasen ("Tolle Strategie!"). Sag was ehrlich ist, nicht was nett ist.
- Vorgreifende Phase-Sprünge. Auch wenn Phase 2 in 30 Min fertig wäre, wenn Phase 1 nicht durch ist, ist Phase 2 nicht dran.
- Über-Erklärungen. Moritz baut Trading-Bots seit Monaten und ist BWL-Student im 2. Semester mit Python-Background. Sprich auf Augenhöhe.

## Bei Session-Start

Mach immer in dieser Reihenfolge:
1. `MASTERPLAN.md` lesen (Section 10 für aktuelle Phase)
2. `git log --oneline -20` (was wurde zuletzt gemacht)
3. `pytest tests/ --tb=no -q` (ist der aktuelle Stand grün?)
4. **Dann** Moritz fragen, was als nächstes ansteht
