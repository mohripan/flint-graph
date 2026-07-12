from fastapi import APIRouter

from atlas_rag.api.routes import documents, health, tenants

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(tenants.router)
api_router.include_router(documents.router)