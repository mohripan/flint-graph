from fastapi import APIRouter

from atlas_rag.api.routes import documents, graph, health, tenants

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(tenants.router)
api_router.include_router(documents.router)
api_router.include_router(graph.router)