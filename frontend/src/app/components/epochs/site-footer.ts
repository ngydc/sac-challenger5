import { Component, computed, inject } from '@angular/core';
import { EpochsStore } from '../../core/services/epochs-store.service';

/** DOIs per release (CLAUDE.md, from docs/spherex/irsa-dr1-overview.md and irsa-quick-release-overview.md). */
const RELEASES: { prefix: string; name: string; doi: string }[] = [
  { prefix: 'spherex_dr1_cube', name: 'DR1 All-Sky Cube', doi: '10.26131/IRSA679' },
  { prefix: 'spherex_dr1', name: 'DR1 spectral images', doi: '10.26131/IRSA678' },
  { prefix: 'spherex_qr3', name: 'QR3', doi: '10.26131/IRSA662' },
  { prefix: 'spherex_qr2', name: 'QR2', doi: '10.26131/IRSA652' },
  { prefix: 'spherex_qr1', name: 'QR1', doi: '10.26131/IRSA629' },
];

@Component({
  selector: 'app-site-footer',
  template: `
    <footer class="site-footer">
      <p>
        This publication makes use of data products from the Spectro-Photometer for the History of
        the Universe, Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint project of
        the Jet Propulsion Laboratory and the California Institute of Technology, and is funded by
        the National Aeronautics and Space Administration.
      </p>
      <p>
        Data releases used{{ fromResult() ? '' : ' by this tool' }}:
        @for (r of used(); track r.doi; let last = $last) {
          SPHEREx {{ r.name }},
          <a [href]="'https://doi.org/' + r.doi" target="_blank" rel="noopener">doi:{{ r.doi }}</a
          >{{ last ? '.' : ';' }}
        }
        Data via
        <a href="https://irsa.ipac.caltech.edu/Missions/spherex.html" target="_blank" rel="noopener"
          >NASA/IPAC IRSA</a
        >.
      </p>
    </footer>
  `,
})
export class SiteFooter {
  private readonly s = inject(EpochsStore);
  protected readonly fromResult = computed(() => (this.s.result()?.collections.length ?? 0) > 0);

  /** The releases of the collections the shown result was searched in; DR1 + QR3 before any result. */
  protected readonly used = computed(() => {
    const cols = this.s.result()?.collections ?? ['spherex_dr1', 'spherex_qr3'];
    const out: typeof RELEASES = [];
    for (const c of cols) {
      const r = RELEASES.find((x) => c.startsWith(x.prefix));
      if (r && !out.includes(r)) out.push(r);
    }
    return out;
  });
}
