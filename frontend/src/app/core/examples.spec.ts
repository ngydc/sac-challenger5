import { EXAMPLES, SEARCH_HINTS } from './examples';

describe('SEARCH_HINTS', () => {
  it('uses only ASCII, so the backend (astropy) can read every hint as typed', () => {
    for (const h of SEARCH_HINTS) expect(h).toMatch(/^[\x20-\x7e]+$/);
  });

  it('names only example targets and gives coordinates in more than one form', () => {
    const names = SEARCH_HINTS.filter((h) => !/^[\d+-]/.test(h));
    for (const n of names) expect(EXAMPLES.some((e) => e.name === n)).toBe(true);
    expect(SEARCH_HINTS.some((h) => /h.*m.*s/.test(h))).toBe(true);
    expect(SEARCH_HINTS.some((h) => /^\d+\.\d+ \d+\.\d+$/.test(h))).toBe(true);
    expect(SEARCH_HINTS.some((h) => /^\d+:\d+:/.test(h))).toBe(true);
  });
});
