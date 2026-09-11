# Safelink Lift Simulator — v3

Two processes. **FastAPI** owns the domain and the files; **Streamlit** is the
front end and reaches the domain only over HTTP. The OrcaFlex external
function speaks the same API, so the contract is exercised every day rather
than only when OrcaFlex runs.

```
browser ──► Streamlit (8501)  ──HTTP──►  FastAPI (127.0.0.1:8000) ──► core/ ──► data/
OrcaFlex EF ──────────────────HTTP──────►
```

Architecture: `05-v2-fastapi-architecture.md`; deployment:
`06-deployment-internal.md`.

## Run

```
pip install -r requirements.txt
python serve.py api                  # start this FIRST
streamlit run app.py                 # http://localhost:8501/
python tests/run_all.py              # 6 physics self-tests + 31 tests
```

On Windows, double-click **Start Simulator.vbs** (no window at all) or
`run.bat` (a console appears for a few seconds, then closes by itself). Either
one starts **both** processes through `serve.py` with `pythonw` — no console
attached, so nothing dies when the launcher exits — waits for `/api/health`,
then for `/_stcore/health`, opens the browser and quits. **Stop Simulator.vbs** / `stop.bat` stops it via the PID in
`logs/server.pid`.

## What is real and what is not

| | |
|---|---|
| **Real** | the 6 ported physics modules and their self-tests; sea temperature and hydrostatic pressure; the registry; cases; the API contract |
| **Placeholder** | everything the solver produces — pressures, stroke, moles, KPIs, verdict. `placeholder: true` in every result, badged in the UI |

`Calculate.vi` is not reverse-engineered yet. `core/engine/placeholder.py` says
exactly which columns are synthetic and how to swap in the real solver: keep
`simulate(unit, case) -> SimResult` and fill the body.

## Layout

```
app.py     Streamlit entry: logo, user card, gate, router, the one outage banner
ui/        client (the whole boundary), data (caches), views, dialogs,
           charts, auth, help_text, theme
api/       FastAPI: routers, the pydantic contract, current_user
core/      engine/ (Protocol + placeholder), physics/ x6, registry, cases, hashing
data/      units.json, unit_status.json, cases/<owner>/<id>.json
jobs/      asana_sync.py - cron 06:00, writes unit_status.json (stub)
docs/      reference-ui.html - the hand-built UI this was designed from
tests/
```

**Four rules make the split real** — `tests/test_isolation.py` enforces all of
them, because each has a failure mode that stays invisible until it bites:

1. `ui/` and `app.py` never import `core`. If they could, someone would, and
   then the solver runs inside Streamlit's rerun loop and `data/` has two
   writers again.
2. `ui/client.py` is the only module that speaks HTTP. One place to change
   when the base URL or the auth header changes.
3. The UI writes nothing under `data/`. The API is the single writer.
4. `core/` imports neither framework, and `api/schemas.py` stays pure
   pydantic — the UI imports those models directly, so one definition of the
   contract serves both sides.

**Every API call from the UI is cached or behind a button.** Streamlit reruns
the whole script on every widget change; an uncached call would mean a solve
per keystroke. That is the single biggest trap in this design.

## Things that are easy to break

- **No module-level mutable state in `core/`.** Caches, global `np.seterr`,
  the `plt.` state machine — any of them lets two concurrent solves
  contaminate each other. `tests/test_concurrency.py` guards this.
- **Add to compare is gated on `input_hash`.** A case is inputs *together
  with* the results they produced; the button must stay off whenever the rail
  has moved since the run.
- **No `cases/index.json`.** An index is a read-modify-write on shared state
  and loses updates. Listing scans the directory.
- **Case ids come from the server**, never from the name. Two people both
  saving "Test 1" is normal.
- **`/api/simulate` is `def`, not `async def`.** The solve is CPU-bound; an
  `async def` body blocks the event loop for the whole solve.
- **The API binds 127.0.0.1, never 0.0.0.0.** It has no authentication. Only
  the Streamlit port is meant to be reachable from other machines.
- **Nothing user-scoped in `st.cache_resource`.** Streamlit runs one process
  for everybody; that cache is shared, and the symptom of getting this wrong
  is "I can see someone else's case".

## Raw HTML: `st.html`, never `st.markdown`

`st.markdown` runs the Markdown parser even with `unsafe_allow_html=True`, and
on some versions that splits a one-line `<div>` into separate blocks — a flex
row silently becomes three stacked lines. `st.html` has no parser in the way.
`tests/test_ui_contract.py` fails the build if `unsafe_allow_html` reappears.

For the same reason the title row, the user card, the KPI tiles and the
verdict carry **inline** styles rather than classes from the injected
stylesheet: an injected `<style>` block is one more thing that can go missing,
and when it does the layout collapses silently. `ui/theme.py` is the one place
that still injects CSS, for things inline styles cannot reach (Streamlit's own
containers).

Dialogs are opened from the **top level of `app.py`**, never from inside
`with st.sidebar:`. Buttons only record which dialog to open.

## Pop-outs

Unit details, Help, Save case, Load case and Sign out are **modal dialogs**
(`ui/dialogs.py`). Not browser tabs: a Streamlit session is per tab, so a new
tab would arrive signed out and knowing nothing about the current selection.
The reference UI used modals for these too — only Compare ever opened a tab.

The wordmark supplied by Safelink is white + yellow, made for a dark
background. It is placed on a dark chip rather than recoloured, so the brand
colours stay exactly as delivered.

## Sessions

Sign out clears the whole session — the next person must not find the previous
one's case on screen. Saved cases live on disk and are kept.

Idle timeout is 5 minutes with 30 seconds of warning (`IDLE_S` / `WARN_S` in
`ui/auth.py`). **Streamlit only sees widget interaction**, so "idle" here means
"no clicks", not "no mouse" — reading a chart for five minutes will sign you
out. That is the accepted cost of not shipping a custom JS component.

## Identity

`st.session_state.user` is a **namespace** for saved cases, not access
control — anyone can type any name. Acceptable while the app is reachable only
from the company network. When it has to be reachable from outside,
`ui/auth.py::gate` (and `api/deps.py::current_user` for the API) are the only
places that change.

## Open

- `Calculate.vi` main loop → the real engine
- Missing solver inputs: vessel RAO, winch stiffness, depth-varying wet
  weight, slam force, landing stiffness
- Asana has no unit field yet — `jobs/asana_sync.py` is a stub
- Unit New / Edit-as-variant / Delete are in the API but not yet in the UI
- Real unit photos and GA drawings into `web/figures/` (showcase images are
  examples)
- Credentials from `External_function_webUI` must go to environment
  variables; confirm that repo is private
