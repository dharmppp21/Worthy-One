from fastapi import APIRouter, Query, Depends

from app.auth import get_current_tenant
from app.embeddings import embedding_service
from app.schemas import SearchResponse, SearchResultItem
from app.storage import store

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResponse)
def search_knowledge(
    q: str = Query(..., min_length=1, max_length=200, description="Search keyword"),
    semantic: bool = Query(False, description="Use semantic search via pgvector if available"),
    tenant_id: str = Depends(get_current_tenant),
) -> SearchResponse:
    """Search across incidents and runbooks by keyword or semantic similarity.

    When `semantic=true`, the query is converted to an embedding vector and
    matched against stored embeddings using pgvector cosine similarity. If
    no embedding service is available (no AI key or local model), the search
    transparently falls back to keyword search.
    """
    if semantic and embedding_service.is_available():
        query_embedding = embedding_service.embed(q)
        if query_embedding:
            semantic_results = store.semantic_search(query_embedding, limit=20)
            if semantic_results:
                results: list[SearchResultItem] = []
                for sr in semantic_results:
                    if sr["entity_type"] == "incident":
                        inc = store.get_incident(sr["entity_id"], tenant_id=tenant_id)
                        if inc:
                            results.append(
                                SearchResultItem(
                                    id=inc.id,
                                    type="incident",
                                    service_name=inc.service_name,
                                    title=inc.title,
                                    summary=inc.summary,
                                    severity=inc.severity,
                                    status=inc.status.value,
                                    created_at=inc.created_at,
                                )
                            )
                    elif sr["entity_type"] == "runbook":
                        rb = store.get_runbook(sr["entity_id"], tenant_id=tenant_id)
                        if rb:
                            results.append(
                                SearchResultItem(
                                    id=rb.id,
                                    type="runbook",
                                    service_name=rb.service_name,
                                    title=rb.title,
                                    summary=rb.description,
                                    severity=None,
                                    status=None,
                                    created_at=rb.created_at,
                                )
                            )
                return SearchResponse(query=q, results=results)

    # Fallback to keyword search
    incidents = store.search_incidents(q, tenant_id=tenant_id)
    runbooks = store.search_runbooks(q, tenant_id=tenant_id)

    results = []
    for inc in incidents:
        results.append(
            SearchResultItem(
                id=inc.id,
                type="incident",
                service_name=inc.service_name,
                title=inc.title,
                summary=inc.summary,
                severity=inc.severity,
                status=inc.status.value,
                created_at=inc.created_at,
            )
        )
    for rb in runbooks:
        results.append(
            SearchResultItem(
                id=rb.id,
                type="runbook",
                service_name=rb.service_name,
                title=rb.title,
                summary=rb.description,
                severity=None,
                status=None,
                created_at=rb.created_at,
            )
        )

    results.sort(key=lambda r: r.created_at, reverse=True)
    return SearchResponse(query=q, results=results)
