# Deep Analysis: was gerechnet wird und warum

> Team-Notiz, keine offizielle SPHEREx-Quelle. Beschreibt den Stand von `backend/app/analysis.py` (`PIPELINE_VERSION` 9) und `backend/app/analysis_jobs.py`. API und Speicherung: `docs/API_ANALYSIS.md`.
> Offizielle Grundlagen, auf die sich der Code stützt: `docs/spherex/user-guide-data-products.md` (HDUs, Einheiten), `docs/spherex/tutorial-intro-spectral-images.md` (Spektral-WCS, Flag-Namen), `docs/spherex/tutorial-psf-in-cutouts.md` (`CRPIX1A`/`CRPIX2A`), `docs/spherex/explanatory-supplement-extracts.md` (Tabelle 16, Flags).

## Ziel in einem Satz

Für eine Himmelsposition pro Detektor und pro **Epoche** (Beobachtungssaison, ca. alle 6 Monate) ein gemitteltes Bild bauen, das zwischen den Epochen **fair vergleichbar** ist, und daraus ein Epochen-RGB, Differenzbilder und Spektren pro Pixel ableiten.

## Das Kernproblem

Bei SPHEREx hat **jeder Pixel eine eigene Wellenlänge** (lineare variable Filter: die Filterfarbe ändert sich über den Detektor). Eine Sternposition wird pro Epoche in jedem der 17 Spektralkanäle eines Detektors nur etwa 1-2-mal gesehen. Würde man einfach alle Bilder einer Epoche mitteln, wäre die Wellenlängen-Mischung in jeder Epoche anders, und ein konstanter Stern mit steilem Spektrum sähe "veränderlich" aus. Deshalb wird **zweistufig** gemittelt: erst pro Kanal, dann über die Kanäle mit gleichen Gewichten in allen Epochen.

## Pipeline Schritt für Schritt

### 1. Epochen bilden
Alle Bilder der Position nach Zeit sortieren; eine Lücke > 30 Tage (`VISIT_GAP_DAYS`) beginnt eine neue Epoche. Repräsentative Zeit einer Epoche = Median der Belichtungszeiten.
*Warum:* SPHEREx beobachtet eine Stelle in Blöcken von Tagen bis Wochen, dazwischen Monate Pause. Innerhalb einer Epoche ist ein Objekt praktisch "gleich", zwischen Epochen kann es sich bewegt oder verändert haben.

### 2. Pro Cutout: Hintergrund abziehen, maskieren, auf ein gemeinsames Gitter bringen
- **Zodiakallicht abziehen:** `img = IMAGE − ZODI` (das Pipeline-Modell des Streulichts von interplanetarem Staub; laut Doku ist es in `IMAGE` *nicht* abgezogen).
- **Maske:** Pixel sind unbrauchbar, wenn `IMAGE` oder `VARIANCE` NaN/≤ 0 ist oder eines der Flags in `BAD_FLAG_NAMES` gesetzt ist (z. B. `OVERFLOW` = Sättigung, `HOT`, `COLD`, `PERSIST`, `STREAK`, `GHOST`, `SNOWBALL`…). Die Bitnummer jedes Flags wird aus dem `FLAGS`-Header **der jeweiligen Datei** gelesen, nicht hart kodiert. `SOURCE` wird bewusst ignoriert (fast überall gesetzt).
- **Reprojektion:** Jedes Bild wird auf ein gemeinsames Gitter umgerechnet (Norden oben, Osten links, 6,15″/Pixel, zentriert auf das Ziel). Für jeden Zielpixel: Himmelskoordinate → Pixel im Cutout über die WCS (World Coordinate System, die Abbildung Pixel ↔ Himmel, inkl. SIP-Verzerrungskorrektur), dann **bilineare Interpolation** (`map_coordinates`, `order=1`) von Bild und Varianz. Maskierte Pixel werden NaN und bleiben NaN.
- **Kanal pro Pixel:** Über `x_parent = 1 + x_cutout − CRPIX1A` (analog y) wird zurückgerechnet, welcher Pixel des *ganzen* Detektors das war, und dort in der offiziellen `CHANNEL_MAP` (Kalibrationsdatei "Spectral Channels") der Spektralkanal nachgeschlagen.

*Warum:* Nur wenn alle Bilder exakt dasselbe Pixelraster haben, kann man pixelweise mitteln und subtrahieren. Die Kanalzuordnung braucht man für die zweistufige Mittelung.

### 3. Himmelshintergrund pro Belichtung (Sky Level)
Nach `IMAGE − ZODI` bleibt pro Belichtung ein kleiner, unterschiedlicher Offset. Er wird als **Median über einen festen Satz "leerer" Pixel** bestimmt und abgezogen.
- **Leere Pixel (`dark_sky`):** Bild 5×5-Median-glätten, dann die dunkelsten 10 % (`SKY_FRACTION`) der gültigen Pixel nehmen.
- Derselbe Pixelsatz gilt für alle Belichtungen und Epochen eines Detektors.

*Warum nicht einfach Sigma-Clipping?* Bei hellen Sternen (R Draconis) füllt der Halo das ganze Feld, dann sind "die meisten Pixel" gar kein Himmel. Die dunkelsten Pixel sind der leerste Himmel, den das Feld hat; da überall dieselben genommen werden, wird ein Rest-Halo in allen Epochen gleich behandelt. Belichtungen mit zu wenigen gültigen Himmelspixeln werden verworfen.

### 4. Stufe 7a: Mitteln pro Spektralkanal und Epoche
Für jede Epoche *e*, jeden Kanal *c* und jeden Pixel werden alle Belichtungen gemittelt, die dort Kanal *c* sahen:

```
I[e,c] = Σ wᵢ·xᵢ / Σ wᵢ               (gewichteter Mittelwert)
V[e,c] = Σ wᵢ²·vᵢ / (Σ wᵢ)²           (Fehlerfortpflanzung)
```

- **Gewicht:** `wᵢ = 1 / Median(Varianz der Belichtung i)`, **eine Zahl pro Belichtung**, nicht pro Pixel.
  *Warum:* Die SPHEREx-Varianz enthält das Photonenrauschen der Quelle selbst. Pixelweise inverse Varianz würde Belichtungen bevorzugen, in denen der Stern zufällig schwächer war, und ihn systematisch zu dunkel machen.
- **Ausreißer-Verwerfung** (nur bei ≥ 3 Beiträgen): verworfen wird, was weiter als 3σ vom Median liegt, mit
  `σ² = vᵢ + (0,2 · Median)²`.
  *Warum der 20-%-Term:* Die PSF (Punktbildfunktion, das Abbild eines Punktes) ist unterabgetastet, d. h. ein Stern ist nur wenige Pixel breit; einzelne Belichtungen desselben Sterns unterscheiden sich daher stärker als ihr Rauschen. Das ist kein Ausreißer.

### 5. Stufe 7b: Kanäle zu einem Bild pro Epoche bündeln
- **Abdeckung:** Ein Kanal gilt in einer Epoche als vorhanden, wenn er ≥ 50 % des Feldes abdeckt. Eine Epoche ist **nutzbar**, wenn sie ≥ 50 % der Kanäle hat.
- **Gemeinsame Kanäle:** Pro Pixel werden nur Kanäle verwendet, die **jede** nutzbare Epoche hat.
- **Spike-Filter** (bei ≥ 5 Kanälen am Pixel): Ein Kanal wird verworfen, wenn
  `|I[e,c] − Median_Kanäle| > 5·√V + 2·|Median_Kanäle|`
  in *irgendeiner* Epoche. Dann fällt er an diesem Pixel in *allen* Epochen raus.
  *Warum:* Die meisten Kanäle haben nur eine Belichtung, Schritt 4 kann dort keine kosmischen Strahlen erkennen. Eine echte Quelle ist aber in allen Kanälen eines Detektors sichtbar, ein Treffer nur in einem.
- **Bündeln:** einfacher Mittelwert über die *K* gemeinsamen Kanäle, gleiche Gewichte in allen Epochen:
  `B[e] = (1/K) Σ_c I[e,c]`, `BV[e] = (1/K²) Σ_c V[e,c]`.
  *Warum:* Gleiche Kanäle + gleiche Gewichte = gleiche effektive Wellenlänge in jeder Epoche. Erst dadurch ist ein Helligkeitsunterschied echt und kein Farbeffekt.

Das gibt es pro Detektor (D1…D6) und einmal für **alle** Detektoren zusammen (Bundle `all`: die Kanäle aller Detektoren werden aneinandergehängt und genauso behandelt).

### 6. Stufe 8: Rest-Hintergrund pro Epochenbild
Noch einmal `dark_sky` auf dem Mittel aller Epochenbilder, dann pro Epoche **sigma-geclippter Median** dieser Pixel abziehen (`clipped_stats`: iterativ Werte > 3σ entfernen, σ = 1,4826 · MAD, MAD = Median der absoluten Abweichungen vom Median, ein ausreißerfestes Maß für die Streuung). Die Streuung σ dient als Rauschmaß der Epoche.
*Warum:* Damit "leerer Himmel = 0" in jeder Epoche gilt und Differenzen nicht von einem Offset dominiert werden.

### 7. Stufe 9: Eine Helligkeits-Skala für alle Epochen (Stretch)
- Weißpunkt `hi` = 99,7-%-Perzentil aller Pixel aller Epochen (mindestens 10σ), Schwarzpunkt = 0.
- **asinh-Stretch:** `t = clip(x/hi, 0, 1)`, `a = clip(3σ/hi, 0,003, 0,5)`, Anzeige `= asinh(t/a) / asinh(1/a)`.
  *Warum asinh:* Bei kleinen Werten fast linear (Rauschen bleibt dunkel), bei großen fast logarithmisch (helle Sterne brennen nicht aus). *Warum eine Skala für alle:* Sonst würde jede Epoche anders gestreckt und ein konstanter Stern sähe veränderlich aus (Anforderung der Challenge für RW Aurigae / R Draconis).

### 8. Epochen-RGB
Drei Epochen werden als Rot / Grün / Blau übereinandergelegt: erste = Rot, die zeitlich der Mitte nächste = Grün, letzte = Blau. Bei nur 2 Epochen: Rot = erste, Grün+Blau = zweite (Cyan). Bei einer: Graustufen.
*Warum:* Unveränderte Quellen sind in allen Kanälen gleich hell und erscheinen **weiß**. Ein bewegter Stern zeigt einen Farbsaum (rot, wo er war; blau, wo er jetzt ist), ein veränderlicher Stern ist einheitlich gefärbt.

### 9. Differenzbilder (in Einheiten der Unsicherheit)
"Total" = letzte − erste nutzbare Epoche; "Steps" = jede nutzbare Epoche minus die vorherige. Für ein Paar (a, b):

```
Δ  = B[b] − B[a]
z0 = Δ / √(BV[a] + BV[b])
s  = robuste Streuung von (z0 − Median5×5(z0)) über die Himmelspixel
m  = Median von Δ über die Himmelspixel
z  = (Δ − m) / √( s²·(BV[a]+BV[b]) + (0,15 · (|B[a]|+|B[b]|)/2)² )
```

- **Empirischer Faktor `s`:** korrigiert die fortgepflanzte Varianz so, dass reines Rauschen wirklich Streuung 1 hat (ersetzt eine exakte Fehlerfortpflanzung durch die Interpolation). Vorher wird ein 5×5-Median abgezogen, damit eine großflächige echte Änderung (Halo von R Draconis) nicht als Rauschen zählt.
- **15-%-Term (`DIFF_RELATIVE_FLOOR`):** gemessen (Barnard's Star, D1/D2): Pixel *unveränderter* Sterne schwanken zwischen Epochen um 11-16 % (unterabgetastete PSF, meist nur eine Belichtung pro Kanal). Ohne diesen Term sähe jeder helle Stern verändert aus.
- **Farbe:** Colormap `RdBu`, abgeschnitten bei ±8σ. Blau = später heller, Rot = früher heller, Weiß = unverändert. Gleiche Konvention wie beim RGB.
- *Warum Steps zusätzlich:* Bei veränderlichen Sternen kann "letzte − erste" ein Hin und Her verdecken; die Steps zeigen, *wann* sich etwas geändert hat. Für Eigenbewegung ist Total stärker (größere Verschiebung).

### 10. Spektrum pro Pixel
Für einen angeklickten Pixel werden die Werte aus Stufe 7a (`I[e,c]`, `σ = √V[e,c]`, Anzahl Beiträge) für jeden Kanal und jede Epoche ausgegeben, zusammen mit Wellenlänge und Kanalgrenzen aus der Tabelle `SPECTRAL_CHANNELS` der Kalibrationsdatei.
*Warum:* Man sieht, ob sich ein Objekt in allen Wellenlängen gleich verändert oder nur in bestimmten (z. B. Molekülbanden bei kühlen Sternen).

## Pixel ohne Daten
Pixel, die in einer verglichenen Epoche keinen gemeinsamen Kanal haben (Bildrand, gesättigter Sternkern), sind **transparent**, nicht schwarz. Schwarz würde "dunkel gemessen" bedeuten.

## Alle Parameter auf einen Blick

| Parameter | Wert | Wofür |
|---|---|---|
| `VISIT_GAP_DAYS` | 30 | Lücke, die eine neue Epoche beginnt |
| `OUTLIER_MIN_N` / `_SIGMA` / `_REL` | 3 / 3,0 / 0,2 | Ausreißer pro Kanal (Schritt 4) |
| `SPIKE_MIN_CHANNELS` / `_SIGMA` / `_REL` | 5 / 5,0 / 2,0 | Einkanal-Spikes (Schritt 5) |
| `CHANNEL_MIN_FIELD_FRACTION` | 0,5 | Kanal gilt als vorhanden |
| `EPOCH_MIN_CHANNEL_FRACTION` | 0,5 | Epoche gilt als nutzbar |
| `SKY_FRACTION` | 0,1 | Anteil dunkelster Pixel als Himmel |
| `STRETCH_HI_PERCENTILE` | 99,7 | Weißpunkt |
| `DIFF_CLIP_SIGMA` | 8,0 | Farbskala der Differenz |
| `DIFF_RELATIVE_FLOOR` | 0,15 | Helligkeitsabhängige Unsicherheit |

Ändert sich einer dieser Werte, ändert sich der Hash `params_key` und alle Produkte werden neu berechnet.
