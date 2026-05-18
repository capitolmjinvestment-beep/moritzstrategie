# MASTERPLAN — Clean H4 Camarilla Reversal Bot

**Owner:** Moritz
**Codebase base:** MjCapital-Scalping (1m scalper, wird als Architektur-Vorlage genutzt)
**Status:** Phase 0 abgeschlossen. Phase 1 beginnt.
**Last updated:** 2026-05-17

---

## 0. Zweck dieses Dokuments

Dieses Dokument ist die **Single Source of Truth** für den Bot. Jede Implementierungsentscheidung wird hier verankert. Wenn Code und Plan divergieren, wird **erst der Plan upgedatet**, dann der Code angepasst – nicht umgekehrt.

Claude Code: lies dieses Dokument bei jeder neuen Session zuerst, bevor du Code anfasst.

---

## 1. Strategie-These (in einem Satz)

> Auf 4h-Crypto-Futures bieten Camarilla H3/L3-Pivot-Levels objektive, mathematisch berechnete Support/Resistance-Zonen, an denen Mean-Reversal-Setups mit hoher Wahrscheinlichkeit funktionieren – bestätigt durch RSI-Extreme und Double-Top/Bottom-Patterns am Pivot-Level.

## 2. Markt & Setup

- **Exchange:** Bitget USDT-Perpetual Futures
- **Symbole:** BTCUSDT, ETHUSDT, SOLUSDT
- **Timeframe:** 4h (24h = 6 Bars)
- **Trading-Stil:** Mean-Reversal an Camarilla-Levels, bidirektional
- **Erwartete Trade-Frequenz:** ~30-100 Trades/Jahr über alle 3 Symbole

## 3. Indikatoren (genau diese 5, nicht mehr)

| # | Indikator | Parameter | Zweck |
|---|-----------|-----------|-------|
| 1 | Camarilla Pivots (Daily) | aus Vortages-OHLC | Objektive S/R-Levels (H1-H4, L1-L4, P) |
| 2 | RSI | 14 | Momentum-Bestätigung (Oversold/Overbought) |
| 3 | ATR | 14 | Stop-Sizing |
| 4 | Double-Top/Bottom Detector | lookback=15, min_sep=3, max_pct_diff=0.015 | Reversal-Pattern-Bestätigung |
| 5 | (Fibonacci nur dokumentarisch, nicht im Code) | — | Mental als TP-Sanity-Check, nicht algorithmisch |

## 4. Camarilla-Berechnung

Aus dem **abgeschlossenen Vortages**-Tagesbar (High H, Low L, Close C):

```
Range R = H − L

H4 = C + R × (1.1 / 2)
H3 = C + R × (1.1 / 4)   ← Short-Reversal-Level
H2 = C + R × (1.1 / 6)
H1 = C + R × (1.1 / 12)
P  = (H + L + C) / 3      ← TP1-Ziel
L1 = C − R × (1.1 / 12)
L2 = C − R × (1.1 / 6)
L3 = C − R × (1.1 / 4)   ← Long-Reversal-Level
L4 = C − R × (1.1 / 2)
```

**Recalc-Regel:** Levels werden beim ersten 4h-Bar nach 00:00 UTC neu berechnet, dann für die nächsten 6 Bars (= 24h) konstant gehalten.

**Look-Ahead-Schutz:** Levels für Tag T basieren AUSSCHLIESSLICH auf dem abgeschlossenen Tag T−1. Nie auf Daten des heutigen Tages.

## 5. Entry-Regeln

### Long-Setup (alle 4 Bedingungen müssen gleichzeitig erfüllt sein)

1. **Pivot-Touch:** Bar-Close ≤ L3 in den letzten 5 Bars
2. **RSI-Oversold:** RSI(14) war innerhalb der letzten 3 Bars unter 30
3. **Double-Bottom-Pattern:** zwei lokale Lows innerhalb der letzten 15 Bars:
   - beide unter oder am L3-Level
   - max 1.5% Preis-Differenz zueinander
   - mind. 3 Bars Abstand zwischen ihnen
4. **Trigger:** aktuelle Bar schließt über dem Zwischenhoch der beiden Lows (Neckline-Breakout) UND RSI > 30

### Short-Setup

Spiegelbildlich an H3 mit RSI > 70 und Double-Top.

## 6. Exit-Regeln

| Trigger | Aktion |
|---------|--------|
| TP1: Preis erreicht zentralen Pivot P | 50% Position schließen |
| TP2 (Long): Preis erreicht H3 | restliche 50% schließen |
| TP2 (Short): Preis erreicht L3 | restliche 50% schließen |
| SL (Long): Preis ≤ min(beide DB-Lows) − 0.5 × ATR(14) | volle Position schließen |
| SL (Short): Preis ≥ max(beide DT-Highs) + 0.5 × ATR(14) | volle Position schließen |
| Time-Stop: 12 Bars (48h) nach Entry ohne TP/SL-Hit | volle Position zum Market schließen |

## 7. Position-Sizing & Risk

- **Risk pro Trade:** 1.5% des aktuellen Equities
- **Position-Size-Formel:**
  ```
  position_size = (equity × 0.015) / |entry_price − stop_price|
  ```
- **Max 1 Position pro Symbol gleichzeitig**
- **Max 2 Positionen gesamt über alle Symbole**
- **Leverage:** 3x (NICHT 10x – Risk-Kontrolle via Sizing, nicht Leverage)
- **Account-Kill-Switches:**
  - Daily Loss Stop: −10% Equity
  - Aggregate Loss Stop: −20% Equity (= alles aus, manueller Restart nötig)

## 8. Datenpipeline-Anforderungen

- Bitget REST-API für historische 4h-Bars (3+ Jahre)
- Bitget WebSocket für Live-Bar-Updates (oder Polling alle 60s, da 4h-TF)
- Daten lokal in Parquet, Schema kompatibel mit dem bestehenden `data/` Modul
- Bar-Gap-Detection: Toleranz auf 4h kalibriert

## 9. Code-Struktur (was wo hin kommt)

### Neu zu erstellende Files

```
src/scalping/indicators/
    camarilla.py              # CamarillaPivots class
    patterns.py               # DoubleTopBottomDetector class

src/scalping/strategies/examples/
    h4_camarilla_reversal.py  # H4CamarillaReversal strategy

conf/data/
    bitget_h4.yaml            # 4h-Data-Config

configs/
    backtest_h4_camarilla.yaml   # Backtest-Config
    live_h4_paper.yaml           # Paper-Trading-Config
    live_h4_real.yaml            # Live-Config (erst nach Phase 5)

tests/unit/indicators/
    test_camarilla.py
    test_patterns.py

tests/unit/strategies/
    test_h4_camarilla_reversal.py
```

### Anzupassende Files

```
src/scalping/data/sources/bitget_rest.py
    Zeilen 106, 156: granularity hardgecodet als "1m" → Parameter

src/scalping/data/loader.py
    granularity-Parameter durchreichen

src/scalping/data/integrity.py
    Bar-Gap-Toleranzen für 4h

src/scalping/cli.py
    H4CamarillaReversal in Strategy-Registry eintragen
```

## 10. Phasen-Plan & Gates

### Phase 1: Daten-Pipeline auf 4h (Tag 1-2)
**Files:** `bitget_rest.py`, `bitget_h4.yaml`, `loader.py`, `integrity.py`
**Gate:** 3 Jahre 4h-Bars für BTC/ETH/SOL lokal als Parquet, keine Lücken, visuell verifiziert

### Phase 2: Indikatoren bauen (Tag 3-4)
**Files:** `camarilla.py`, `patterns.py`, dazugehörige Tests
**Gate:** Unit-Tests grün + Sanity-Plot auf echten Daten visuell ok

### Phase 3: Strategie implementieren (Tag 5-7)
**Files:** `h4_camarilla_reversal.py`, Registry in `cli.py`
**Gate:** Strategie läuft im Backtest über 7 Tage Daten ohne Crash, produziert ≥1 Trade

### Phase 4: Backtest 3 Jahre + Auswertung (Tag 8-14)
**Files:** `backtest_h4_camarilla.yaml`
**Gate (HARTES Gate):**
| Metric | Minimum |
|--------|---------|
| Trade-Count | ≥ 80 |
| Sharpe (out-of-sample) | ≥ 1.0 |
| Max Drawdown | ≤ 30% |
| Profit Factor | ≥ 1.3 |
| Win-Rate | zwischen 35-65% |
| Performance ohne Top-5-Trades | noch positiv |

**Wichtig:** Bei Fail nicht Parameter tunen bis es passt – das ist Overfitting. Max 2-3 fundamentale Iterationen, sonst Strategie verwerfen.

### Phase 5: Walk-Forward + Paper Trading (Tag 15-45)
**Files:** `live_h4_paper.yaml`
**Gate:** 4 Wochen Bitget-Testnet, mind. 5 Trades, Performance grob im Backtest-Erwartungswert

### Phase 6: Live mit Mini-Sizing (ab Tag 46)
**Files:** `live_h4_real.yaml`
**Gate:** 2-3 Monate live, keine Parameter-Änderung mid-flight
**Settings:**
- Start-Equity: 1000 € (=Moritz' Gesamtkapital, erklärtes Risikokapital)
- notional_frac: 0.05
- leverage: 3
- Max-Loss-per-Trade: ~15 € (= 1.5% von 1000 €)

## 11. Regeln, die NICHT verhandelbar sind

1. **Keine Look-Ahead-Bias.** Strategie sieht nur kausal verfügbare Daten.
2. **Keine Parameter-Tuning auf Test-Set.** Walk-Forward oder gar nicht.
3. **Phasen-Gates müssen bestanden werden.** Kein Überspringen.
4. **In Phase 6 keine Live-Parameter-Änderungen** für mindestens 2-3 Monate.
5. **Wenn Gate failt: zurück, nicht tunen.**

## 12. Offene Fragen / Bekannte Risiken

- **Few-trades-problem:** Bei 4h und 3 Symbolen + strikten Filtern könnte Trade-Count zu niedrig für Statistik sein. Falls Phase 4 unter 80 Trades → vor dem Verwerfen prüfen, ob Filter zu eng (z.B. RSI-Schwelle auf 35/65 statt 30/70).
- **Camarilla-Daily-Bar-Quelle:** Bitget-API liefert Daily-Bars in UTC. Sicherstellen, dass Day-Boundaries konsistent mit 4h-Bars sind.
- **Slippage-Modell:** Backtest-Slippage muss realistisch sein. 4h-Bars haben große Spannen – Annahme "fill at close" ist konservativ, prüfen.
- **Funding-Rates:** Bei Hold-Zeiten bis 48h können Funding-Kosten relevant werden. In Backtest-Friction einbauen, falls Edge gegen Funding marginal ist.

## 13. Glossar

- **OOS:** Out-of-sample – Daten, die nicht für Parameter-Tuning verwendet wurden
- **Walk-Forward:** Train auf Periode A, Test auf nachfolgender Periode B, rollend
- **MFE/MAE:** Maximum Favourable / Adverse Excursion – wie weit ging der Trade in Gewinn/Verlust bevor er schloss
- **Bracket-Order:** Entry-Order mit angehängtem TP+SL auf Exchange-Seite
