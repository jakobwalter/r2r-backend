# File: main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import routes

app = FastAPI(title="GraphHopper Proxy API", version="1.0.0")

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8080", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(routes.router, prefix="/api")

@app.get("/")
async def root():
    return {"message": "GraphHopper Proxy API is running"}

# To run the server:
# uv run uvicorn main:app --reload