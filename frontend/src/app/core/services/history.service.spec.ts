import { TestBed } from '@angular/core/testing';
import { HistoryService } from './history.service';

const entry = (query: string) => ({ query, name: null, ra: 1, dec: 2 });

describe('HistoryService', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.resetTestingModule();
  });

  it('keeps the newest search first and offers the last three', () => {
    const h = TestBed.inject(HistoryService);
    ['a', 'b', 'c', 'd'].forEach((q, i) => h.add(entry(q), i));
    expect(h.entries().map((e) => e.query)).toEqual(['d', 'c', 'b', 'a']);
    expect(h.recent().map((e) => e.query)).toEqual(['d', 'c', 'b']);
  });

  it('moves a repeated search to the top instead of duplicating it', () => {
    const h = TestBed.inject(HistoryService);
    h.add(entry("Barnard's Star"), 1);
    h.add(entry('RW Aurigae'), 2);
    h.add(entry("  barnard's star "), 3);
    expect(h.entries().map((e) => e.at)).toEqual([3, 2]);
  });

  it('survives a reload, and can remove and clear', () => {
    TestBed.inject(HistoryService).add(entry('a'), 1);
    TestBed.inject(HistoryService).add(entry('b'), 2);
    TestBed.resetTestingModule();
    const h = TestBed.inject(HistoryService);
    expect(h.entries().length).toBe(2);
    h.remove('A');
    expect(h.entries().map((e) => e.query)).toEqual(['b']);
    h.clear();
    expect(JSON.parse(localStorage.getItem('challenger5.history')!)).toEqual([]);
  });

  it('ignores broken stored data', () => {
    localStorage.setItem('challenger5.history', '{not json');
    expect(TestBed.inject(HistoryService).entries()).toEqual([]);
  });
});
