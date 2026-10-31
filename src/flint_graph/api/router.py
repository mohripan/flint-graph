from fastapi import APIRouter

from flint_graph.api.routes import (
    conversations,
    documents,
    graph,
    health,
    narrative,
    narrative_asset_folders,
    narrative_assets,
    narrative_assistant,
    narrative_characters,
    narrative_layout,
    narrative_releases,
    observability,
    query,
    retrieval,
    tenants,
    workspaces,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(observability.router)
api_router.include_router(workspaces.router)
api_router.include_router(tenants.router)
api_router.include_router(documents.router)
api_router.include_router(graph.router)
api_router.include_router(retrieval.router)
api_router.include_router(query.router)
api_router.include_router(conversations.router)
api_router.include_router(narrative.router)
api_router.include_router(narrative_releases.router)
api_router.include_router(narrative_assistant.router)
api_router.include_router(narrative_layout.router)
api_router.include_router(narrative_characters.router)
api_router.include_router(narrative_assets.router)
api_router.include_router(narrative_asset_folders.router)
