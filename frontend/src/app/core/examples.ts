/**
 * The five challenge test targets.
 *
 * `catalogue` is the J2000 position from docs/PROJECT_OVERVIEW.md section 3 (SIMBAD), shown to the user.
 * The page does not send it as is: it asks GET /api/resolve for the name, which returns the same catalogue
 * position moved to the current year with the proper motion (backend/app/presets.py). That is the position
 * the backend precomputed, so the result appears at once; the catalogue position of a moving star would
 * miss the cache and put the star off-centre.
 *
 * `seen` describes what the precomputed difference pictures actually show (looked at on 2026-11-15, after
 * the colours were swapped; default field of view). Update it if the pictures change, e.g. after a
 * recomputation with new data.
 */
export interface Example {
  name: string;
  short: string;
  what: string;
  catalogue: string;
  seen: string;
}

export const EXAMPLES: Example[] = [
  {
    name: "Barnard's Star",
    short: 'Barnard',
    what: 'a nearby star that moves faster across the sky than any other',
    catalogue: '17h57m48.50s +04d41m36.1s',
    seen:
      'The star is so bright that its centre is blank (saturated). Around the blank core it is blue ' +
      'above and red below: it moved north (up) between the first and the latest epoch.',
  },
  {
    name: 'Epsilon Indi B',
    short: 'ε Indi B',
    what: 'a pair of brown dwarfs, seen as one dot',
    catalogue: '22h04m10.60s −56d46m58.2s',
    seen:
      'A blue–red pair at the centre in D2 to D6, blue at the lower left and red at the upper right: ' +
      'it moved towards the lower left, which is south-east. The blue haze below it in D5 is diffuse ' +
      'light that was brighter in the latest epoch, not the brown dwarf.',
  },
  {
    name: 'WISE 0855-0714',
    short: 'WISE 0855',
    what: 'the coldest known brown dwarf, faint and fast',
    catalogue: '08h55m10.831s −07d14m42.53s',
    seen:
      'Not recognisable: at the centre the Difference view shows only noise, in every detector. Only ' +
      'two epochs cover it so far.',
  },
  {
    name: 'RW Aurigae',
    short: 'RW Aur',
    what: 'a young star whose brightness changes',
    catalogue: '05h07m49.57s +30d24m05.2s',
    seen:
      'Red around the star in D4 to D6: at the longest wavelengths it was brighter in the first epoch ' +
      'than in the latest. In D1 and D2 it is slightly bluish (a little brighter now). One colour, no ' +
      'red–blue pair: a brightness change, no motion.',
  },
  {
    name: 'R Draconis',
    short: 'R Dra',
    what: 'a pulsating giant star that brightens and fades over months',
    catalogue: '16h32m40.23s +66d45m17.9s',
    seen:
      'The centre is blank (saturated). Red all around the star in every detector: it was brighter ' +
      'in the first epoch than in the latest. A brightness change, no motion.',
  },
];

/**
 * Rotating hints in the empty search box: real inputs in every accepted form (name, sexagesimal with
 * h/m/s or colons, decimal degrees), so a new user sees exactly what to type.
 *
 * Coordinates are only given for the two targets that do not move (RW Aurigae, R Draconis; positions from
 * `catalogue` above). The J2000 position of Barnard's Star is about 4.5' away from where the star is now,
 * outside the default field of view, so the moving targets appear by name only. ASCII "-" and "+" only:
 * the backend reads coordinates with astropy (backend/app/resolver.py).
 */
export const SEARCH_HINTS: readonly string[] = [
  "Barnard's Star",
  '05h07m49.57s +30d24m05.2s',
  'Epsilon Indi B',
  '248.1676 66.7550',
  'WISE 0855-0714',
  '16:32:40.23 +66:45:17.9',
];

/** How long each hint stays (ms): long enough to read a coordinate pair. */
export const SEARCH_HINT_MS = 4000;
