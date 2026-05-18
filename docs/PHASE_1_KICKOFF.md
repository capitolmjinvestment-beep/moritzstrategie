# PHASE 1 KICKOFF — Daten-Pipeline auf 4h

**Diesen Prompt in Claude Code reinkopieren, um Phase 1 zu starten.**

---

Hi Claude. Wir starten Phase 1 des H4 Camarilla Reversal Bots.

Bitte mach in dieser Reihenfolge:

1. Lies `MASTERPLAN.md` komplett — das ist die Single Source of Truth für den Bot.
2. Lies `CLAUDE.md` — das sind deine Working-Instructions, sehr wichtig.
3. Lies diese drei Files, um den Code-Stand zu verstehen:
   - `src/scalping/data/sources/bitget_rest.py` (besonders Zeilen 100-160)
   - `src/scalping/data/loader.py`
   - `src/scalping/data/integrity.py`
4. Lies `conf/data/` und schau dir ein bestehendes Data-Config-File an (z.B. `bitget_btcusdt.yaml` oder ähnlich), damit du das Hydra-Schema kennst.

Dann brief mich kurz (max. 10 Zeilen):
- Was hast du im Daten-Layer gesehen?
- Wo genau ist `granularity` hardgecodet (Zeilen)?
- Wie schlägst du vor, das zu parametrisieren? Drei Optionen mit Pros/Cons.

**Mach noch keinen Code-Change.** Erst Verständnis, dann Plan, dann Code.

Phase-1-Goal (aus `MASTERPLAN.md` Section 10):
- 3 Jahre 4h-Bars für BTCUSDT, ETHUSDT, SOLUSDT von Bitget runtergeladen
- Lokal als Parquet im bestehenden `data/`-Schema
- Keine Bar-Gaps, visuell verifiziert
- `bitget_rest.py` granularity-parametrisiert (statt hardcoded "1m")
- Neues Config-File `conf/data/bitget_h4.yaml`

Was du explizit NICHT machen sollst:
- Indikatoren oder Strategie anfassen (das ist Phase 2 und 3)
- Neue Dependencies hinzufügen ohne Rückfrage
- Tests weglassen
- Look-Ahead-Bias-Risiken ignorieren

Los geht's. Erstmal nur das Briefing.
