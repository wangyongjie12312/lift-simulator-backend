# Safelink Lift Simulator — backend

**FastAPI** owns the domain and the files. The Streamlit front end
([Lift-simulator-frontend](https://github.com/wangyongjie12312/Lift-simulator-frontend))
and the OrcaFlex external function both speak this API.

```
Streamlit UI ──HTTP──►  FastAPI (Railway) ──► core/ ──► data/
OrcaFlex EF  ──HTTP──►
```

## Run

```
pip install -r requirements.txt
uvicorn api.main:app --port 8000     # http://127.0.0.1:8000/health
python tests/run_all.py              # physics self-tests + API tests
```

Railway starts it from `railway.toml`. Routes have no `/api` prefix.
Allowed front-end origins are `ALLOWED_ORIGINS` in `api/main.py`.

## What is real and what is not

| | |
|---|---|
| **Real** | the 6 ported physics modules and their self-tests; sea temperature and hydrostatic pressure; the registry; cases; the API contract |
| **Placeholder** | everything the solver produces — pressures, stroke, moles, KPIs, verdict. `placeholder: true` in every result |

`Calculate.vi` is not reverse-engineered yet. `core/engine/placeholder.py` says
exactly which columns are synthetic and how to swap in the real solver: keep
`simulate(unit, case) -> SimResult` and fill the body.

## Layout

```
api/       FastAPI: routers, the pydantic contract, current_user
core/      engine/ (Protocol + placeholder), physics/ x6, registry, cases, hashing
data/      units.json, unit_status.json, cases/<owner>/<id>.json
jobs/      asana_sync.py - cron 06:00, writes unit_status.json (stub)
tests/
```

- `core/` imports neither framework (`tests/test_isolation.py`).
- `api/schemas.py` stays pure pydantic — the front end keeps a copy in
  `ui/schemas.py`. Change both together.

## Things that are easy to break

- **No module-level mutable state in `core/`.** Caches, global `np.seterr`,
  the `plt.` state machine — any of them lets two concurrent solves
  contaminate each other. `tests/test_concurrency.py` guards this.
- **No `cases/index.json`.** An index is a read-modify-write on shared state
  and loses updates. Listing scans the directory.
- **Case ids come from the server**, never from the name. Two people both
  saving "Test 1" is normal.
- **`/simulate` is `def`, not `async def`.** The solve is CPU-bound; an
  `async def` body blocks the event loop for the whole solve.
- **The API has no authentication.** `X-User` is a namespace, not access
  control; `api/deps.py::current_user` is the one place to change.

## Open

- `Calculate.vi` main loop → the real engine
- Missing solver inputs: vessel RAO, winch stiffness, depth-varying wet
  weight, slam force, landing stiffness
- Asana has no unit field yet — `jobs/asana_sync.py` is a stub
- Credentials from `External_function_webUI` must go to environment
  variables; confirm that repo is private
