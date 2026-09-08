from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from documents import router as documents_router
from mapping import router as mapping_router
from search import router as search_router
from qa import router as qa_router
from auth import router as auth_router, init_users_db


app = FastAPI()
init_users_db()
app.include_router(auth_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(mapping_router)
app.include_router(search_router)
app.include_router(qa_router)
app.include_router(documents_router)

@app.get("/")
def root():
    return {"status": "ok"}
