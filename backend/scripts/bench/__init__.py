"""Benchmarks for fetching and caching SPHEREx data (branch fetch-speed-investigation).

Each module is one short test of one approach; results go to backend/out/bench/<name>.json.
Run from backend/ (needs `docker compose up -d db` with a cached Barnard's Star coverage):
    .venv\\Scripts\\python -m scripts.bench.t1_irsa_cutout
    .venv\\Scripts\\python -m scripts.bench.t2_range_cutout
    .venv\\Scripts\\python -m scripts.bench.t3_coverage
    .venv\\Scripts\\python -m scripts.bench.t4_cache
Summary of the results: docs/FETCH_SPEED.md.
"""
