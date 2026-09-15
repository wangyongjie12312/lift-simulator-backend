# api/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import errors, state
from api.routers import cases, health, public, simulate, units

app = FastAPI()
errors.install(app)   # RegistryError -> 409, CaseError -> 404/400 instead of 500

# 允许的前端来源
ALLOWED_ORIGINS = [
    "https://liftsim.streamlit.app",  # 生产
    "http://localhost:8501",           # 本地开发
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(public.router)
app.include_router(simulate.router)
app.include_router(cases.router)
app.include_router(units.router)


@app.on_event("startup")
def start_warm_up() -> None:
    state.warm_up()