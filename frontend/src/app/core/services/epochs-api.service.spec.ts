import { EpochsApi } from './epochs-api.service';

const p = { ra: 10, dec: 20, fov: 0.08, pmra: null, pmdec: null, pm_epoch: null };

describe('EpochsApi.diffUrl', () => {
  const api = new EpochsApi();

  it('gives the Total picture without a step', () => {
    expect(api.diffUrl(p, 'D1', 'k1')).toContain('/analysis/D1/diff.png?');
    expect(api.diffUrl(p, 'D1', 'k1', null)).toContain('/analysis/D1/diff.png?');
  });

  it('treats step 0 as a step, not as Total', () => {
    const url = api.diffUrl(p, 'D1', 'k1', 0);
    expect(url).toContain('/analysis/D1/steps/0.png?');
    expect(url).not.toContain('diff.png');
    expect(api.diffUrl(p, 'all', '', 2)).toContain('/analysis/all/steps/2.png?');
  });
});
