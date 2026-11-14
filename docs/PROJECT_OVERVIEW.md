# Planet X and SPHEREx — Project Overview

NASA Space Apps Challenge 2026 · Difficulty: Advanced · Subjects: Astrophysics, Planets & Moons, Software
Challenge page: https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/

## 1. The goal in one paragraph

Build a **public-facing web tool** that shows SPHEREx images of any patch of sky as a **short "blink" animation over time**, so anyone can spot objects that move or vary. The user enters sky coordinates (RA/Dec). The tool fetches SPHEREx images covering that spot, orders them by observation time and plays them like a little video. Moving objects (asteroids, comets, nearby stars, brown dwarfs) show up as points of light that shift between frames.

This is the SPHEREx equivalent of **WiseView**, the tool Backyard Worlds volunteers use to find brown dwarfs in WISE data.

## 2. Why it matters (background)

- Motion between images is how many objects are found. Pluto was discovered this way. Most known comets and brown dwarfs were found by volunteers using projects like backyardworlds.org.
- SPHEREx has mapped the whole sky every six months since May 2025, in **102 near-infrared bands**. It sees more than a billion objects and is especially sensitive to hydrogen-, water-, CO2- and CO-rich objects.
- There is too much data for any one person or program to examine, so the challenge asks for tools that let many people help.

## 3. Required deliverable

| Requirement | Notes |
|---|---|
| Web tool, public-facing | Anyone should be able to use it without installing anything |
| Input: RA + Dec of a sky patch | Sexagesimal (e.g. `08h55m10.831s -07d14m42.53s`) and ideally decimal degrees |
| Output: time series of images as a "little video" | Blink/flipbook that makes moving objects easy to spot |

### Required test targets

| Target | What it is | Position, J2000 (SIMBAD) | Proper motion | Expected motion in SPHEREx | Approx. position late 2026 |
|---|---|---|---|---|---|
| Barnard's Star | Nearby star, highest proper motion known | 17h57m48.50s +04d41m36.1s | 10.39″/yr | ~1.7 px/yr | 17h57m47.06s +04d46m14.9s |
| Epsilon Indi B (Ba/Bb) | Pair of brown dwarfs orbiting a star | 22h04m10.60s −56d46m58.2s | 4.68″/yr | ~0.8 px/yr | 22h04m23.63s −56d48m04.6s |
| WISE 0855 | Fast-moving brown dwarf (coldest known) | brief: 08h55m10.831s −07d14m42.53s (epoch ~2010) | 8.15″/yr | ~1.3 px/yr | 08h55m01.85s −07d14m31.3s |
| RW Aurigae | Variable star (young, T Tauri type) | 05h07m49.57s +30d24m05.2s | ~0.02″/yr (static) | none, test **brightness** change | same |
| R Draconis | Variable star (Mira type) | 16h32m40.23s +66d45m17.9s | ~0.02″/yr (static) | none, test **brightness** change | same |

Positions and proper motions are from SIMBAD. The late-2026 column is our own propagation (epoch 2026.9) and should be checked against the actual SPHEREx images. Pixel counts assume 6.2″ pixels.

**Things to know about the targets:**
- **Catalog positions are stale for movers.** Barnard's Star has moved about 4.7′ since J2000 and WISE 0855 about 3.5′. Typing the catalog coordinates into the tool will put the target off-center or outside a small field of view. The tool should offer a proper-motion option, or the demo should use the current-epoch positions above with a wide enough field.
- **Epsilon Indi B is about 6.7′ from its host star (Epsilon Indi A).** A field of view of ~10′ shows both. The two brown dwarfs Ba and Bb are within about 1–2″ of each other, so they are **unresolved** at SPHEREx's 6″ pixels and appear as one source.
- **RW Aur and R Dra test variability, not motion.** They should show brightness changes between epochs (R Dra is a long-period Mira variable), so the tool needs a stretch that stays consistent across frames.

The tool should show the motion or brightness change for each of these. This is the natural demo and acceptance test.

## 4. Optional features (the "kudos" list)

Roughly in order of value for the effort, our suggestion:

1. **URL-addressable queries** (e.g. `?ra=...&dec=...&fov=...`). This makes the tool embeddable and shareable and is cheap to build.
2. **Adjustable field of view.** A larger field tracks faster movers, but costs more transfer time.
3. **Band handling.** Co-add images per detector array (6 arrays) to improve signal-to-noise. Let the user pick bands or arrays.
4. **Add/subtract images** from different epochs to highlight movers.
5. **Overlays** from other surveys, namely **Gaia DR3** and **WISE** (Aladin Lite can do this).
6. **Metadata display**, such as contamination flags and observation dates.
7. **On-the-fly spectra** for a clicked source (flagged as "extra kudos").
8. **Easy to update** with new SPHEREx releases. This is a design requirement, not just a feature. Avoid hard-coding datasets.

Suggested libraries from the brief: Astropy tools for data handling, and **Aladin / Aladin Lite** (CDS Strasbourg) for display.

## 5. SPHEREx key facts

- Spectral range **0.75–5.0 µm**, split across **6 detector arrays**, each with its own linear variable filter. Each array covers 17 channels, so **6 × 17 = 102 bands**.
- Each array is 2040 × 2040 pixels at **6.15″ per pixel** (IRSA's figure; other sources round to 6.2″), so SPHEREx has coarse pixels compared with WISE or Gaia imaging.
- Resolving power is R ≈ 35–41 for bands 1–4 and R ≈ 112–128 for bands 5–6. See [RESOURCES.md](RESOURCES.md#2-data-format) for the band table.
- The wavelength **changes across each image** (linear variable filters). Every frame has one effective wavelength at the target's position.
- SPHEREx launched in March 2025 for a planned two-year mission. IRSA publishes new images weekly. Current releases are **DR1 and QR3** (collections `spherex_dr1` and `spherex_qr3`). The older QR2 is no longer searchable.
- Full-sky coverage every 6 months. Each sky position is seen in different bands at different times. **This matters for the design:** a single "epoch" is not one clean image of the patch in one band. Different bands of the same spot come from different exposures at different moments, so we have to decide how to build a time series (per band, per detector array, or per time bin).
- Sources: [SPHEREx pipeline paper](https://arxiv.org/pdf/2511.15823), [Spectral response paper](https://arxiv.org/pdf/2602.09139), [IRSA SPHEREx page](https://irsa.ipac.caltech.edu/Missions/spherex.html).

> Detailed notes on every listed resource (IRSA, tutorial notebooks, WiseView, Gaia, CSA/NEOSSat) are in [RESOURCES.md](RESOURCES.md).

## 6. Open questions and risks for the team

1. **What is one "frame"?** (see section 5) We need to choose how to turn irregular multi-band exposures into a time-ordered blink sequence.
2. **Latency.** We measured about 10 s per cutout and 3 s for an SIA2 search, and a TAP query once took 82 s. Fetch in parallel, cache, and show frames as they arrive.
3. **A backend is needed.** IRSA's services send no CORS headers, so a browser page can't call them directly. We need a thin proxy (e.g. FastAPI + astropy). It can also drop the large PSF extension: 96% of a 4 MB cutout is PSF, while the image layers are only ~55 KB. See [RESOURCES.md, section 4](RESOURCES.md#4-what-we-measured-and-what-it-means-for-the-design).
4. **Coarse pixels (~6″).** Fast movers like WISE 0855 should still be visible, but detection of subtle motion needs good stretch controls and ideally image subtraction.
5. **Collection and endpoint names change between releases.** Keep them in config.
6. **Time pressure.** Event dates are Nov 14–15, so build the required MVP first (coordinates → cutouts → blink player, tested on the 5 targets), then add optional features.

7. **Proper motion vs. coordinate input.** See the notes under the test targets. Decide whether the tool takes a position at a given epoch and shifts it, or simply asks for a wide field.
8. **How many epochs exist for a given patch?** IRSA's cutout tutorial found 84 images in a single detector for the galaxy M101, but many were only minutes apart (consecutive exposures), so they can't show motion by themselves. Real motion needs images from different planning periods, weeks to months apart. Check how many distinct epochs the five test targets have.
9. **Hosting and public access.** "Public-facing" needs a place to host the front end (and backend, if any), and respect for IRSA's rate limits and terms of use. Not yet researched.

## 8. What this overview does not cover

- **Judging criteria and submission requirements** for Space Apps (deliverables, demo format, deadlines). These aren't in the challenge text we have. Check the participant guides and FAQs at spaceappschallenge.org/resources/.
- **The official page text.** The challenge page loads its content with JavaScript, so this overview is based on the text pasted from it, not on an automated fetch. If the page is updated ("More resources may be added before the hackathon begins"), re-check it.
- **Team roles, tech stack and architecture.** Not decided yet. See the open questions above.

## 9. Glossary

- **RA / Dec:** right ascension and declination, the sky's longitude and latitude. RA is often written in hours (h m s), Dec in degrees (d m s).
- **Epoch:** the date a position is valid for. Moving objects have different positions at different epochs.
- **Proper motion:** an object's apparent motion across the sky, in arcseconds per year.
- **Field of view (FOV):** the width of the sky patch shown.
- **Co-add:** combining several images, usually by averaging, to reduce noise.
- **Spectral image:** a SPHEREx exposure in which each part of the detector sees a different wavelength, because of the linear variable filter.
- **FITS / WCS:** the standard astronomy image file format, and the information in it that maps pixels to sky coordinates.
- **Blink comparison:** flipping quickly between images of the same field so that anything that moved appears to jump.

## 10. Suggested MVP checklist

- [ ] Query IRSA for SPHEREx spectral images covering an RA/Dec (SIA2 or TAP)
- [ ] Fetch cutouts for a chosen field of view
- [ ] Sort by observation time, normalize and stretch, render frames
- [ ] Blink/animation player in the browser with play/pause/step
- [ ] RA/Dec entry form, plus URL query parameters
- [ ] Verify on Barnard's Star, Epsilon Indi B, WISE 0855, RW Aur, R Dra
- [ ] Optional: Gaia/WISE overlays (Aladin Lite), per-array co-adds, difference images, spectra
