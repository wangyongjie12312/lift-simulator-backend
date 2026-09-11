"""Safelink Lift Simulator — Streamlit front end.

    python serve.py api          the domain; start this first
    streamlit run app.py         this

The UI holds no domain code and touches no files under data/. Everything goes
through the API, so there is one solver, one contract exercised daily, and one
writer on the case store.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

FIG = Path(__file__).resolve().parent / "web" / "figures"
st.set_page_config(page_title="Lift Simulator", page_icon=FIG / "sl_logo-init_p.png",
                   layout="wide", initial_sidebar_state="expanded")

from ui import auth, chrome, client, dialogs, theme as T, views   # noqa: E402

# The supplied wordmark is white + yellow, made for a dark background. It is
# used unchanged, on a dark chip, rather than recoloured.

T.inject()

st.session_state.setdefault("compare", [])
st.session_state.setdefault("page", "sim")
st.session_state.setdefault("dialog", None)

if not auth.gate():
    st.stop()

auth.check_idle()
auth.touch()

msg = st.session_state.pop("toast_msg", None)
if msg:
    st.toast(msg)

# ---- sidebar head -------------------------------------------------------
with st.sidebar:
    _,lc,_ = st.columns([1,3,1])
    with lc:
        st.image(str(FIG / "sl_logo.png"), width="stretch")
    # add vertical space between logo and title row, so that the title row is not too close to the logo
    st.html('<div style="height:.6rem"></div>')
    chrome.sidebar_head(f"Welcome, {st.session_state.user}!")
    c1, c2 = st.columns(2)
    # Buttons only RECORD which dialog to open; the dialog itself is opened at
    # the bottom of this file, outside every layout container. Opening one from
    # inside `with st.sidebar` leaves its placement up to the version.
    if c1.button("Help", width = "stretch", help="What this tool does and how to drive it"):
        st.session_state.dialog = "help"
    if c2.button("Sign out", width = "stretch"):
        st.session_state.dialog = "signout"
    st.divider()

chrome.title_row(st.session_state.page)
auth.idle_watch()

# ---- pages --------------------------------------------------------------
# A backend that goes away mid-session must read as "the backend is down",
# not as a stack trace in the middle of the page.
req = None
try:
    if st.session_state.page == "sim":
        req = views.build_request()      # the rail is only part of Simulator
        views.simulator(req)
    else:
        views.compare()
except client.Unreachable:
    st.error("Lost contact with the simulator backend. It may have been "
             "stopped, or it crashed — see `logs/api.log`.", icon="⛔")
    if st.button("Try again"):
        views.data.clear_caches()
        st.rerun()
except client.ApiError as exc:
    st.error(f"The backend refused the request: {exc.message}", icon="⚠️")

# ---- dialogs, at the top level ------------------------------------------
which = st.session_state.dialog
if which:
    st.session_state.dialog = None
    if which == "help":
        dialogs.help_doc()
    elif which == "signout":
        dialogs.sign_out()
    elif which == "unit":
        dialogs.unit_details()
    elif which == "units":
        dialogs.manage_units()
    elif which == "save":
        dialogs.save_case()
    elif which == "load":
        dialogs.load_case()
