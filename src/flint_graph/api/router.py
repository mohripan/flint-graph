from fastapi import APIRouter

from flint_graph.api.routes import documents, graph, health, query, retrieval, tenants, workspaces

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(workspaces.router)
api_router.include_router(tenants.router)
api_router.include_router(documents.router)
api_router.include_router(graph.router)
api_router.include_router(retrieval.router)
api_router.include_router(query.router)
