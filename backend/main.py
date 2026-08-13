from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mapping import router as mapping_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(mapping_router)

@app.get("/")
def root():
    return {"status": "ok"}