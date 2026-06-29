from fastapi import APIRouter, HTTPException, Depends

from app.auth import get_current_tenant
from app.embeddings import embedding_service
from app.schemas import Runbook, RunbookCreate, RunbookUpdate
from app.storage import store

router = APIRouter(tags=["runbooks"])


@router.post("/runbooks", response_model=Runbook)
def create_runbook(data: RunbookCreate, tenant_id: str = Depends(get_current_tenant)) -> Runbook:
    """Create a new runbook for a service."""
    from datetime import datetime, timezone
    from uuid import uuid4

    now = datetime.now(timezone.utc)
    runbook = Runbook(
        id=str(uuid4()),
        tenant_id=tenant_id,
        service_name=data.service_name,
        title=data.title,
        description=data.description,
        steps=data.steps,
        created_at=now,
        updated_at=now,
    )
    store.create_runbook(runbook)
    if embedding_service.is_available():
        text_to_embed = f"{runbook.title}. {runbook.description}. {' '.join(runbook.steps)}"
        embedding = embedding_service.embed(text_to_embed)
        if embedding:
            store.store_embedding("runbook", runbook.id, embedding)
    return runbook


@router.get("/runbooks", response_model=list[Runbook])
def list_runbooks(service_name: str | None = None, tenant_id: str = Depends(get_current_tenant)) -> list[Runbook]:
    """List all runbooks for the authenticated tenant, optionally filtered by service."""
    return store.list_runbooks(tenant_id=tenant_id, service_name=service_name)


@router.get("/runbooks/{runbook_id}", response_model=Runbook)
def get_runbook(runbook_id: str, tenant_id: str = Depends(get_current_tenant)) -> Runbook:
    """Get a single runbook by ID."""
    runbook = store.get_runbook(runbook_id, tenant_id=tenant_id)
    if runbook is None:
        raise HTTPException(status_code=404, detail="Runbook not found")
    return runbook


@router.patch("/runbooks/{runbook_id}", response_model=Runbook)
def update_runbook(runbook_id: str, data: RunbookUpdate, tenant_id: str = Depends(get_current_tenant)) -> Runbook:
    """Update a runbook's title, description, or steps."""
    runbook = store.update_runbook(
        runbook_id,
        title=data.title,
        description=data.description,
        steps=data.steps,
        tenant_id=tenant_id,
    )
    if runbook is None:
        raise HTTPException(status_code=404, detail="Runbook not found")
    return runbook


@router.delete("/runbooks/{runbook_id}")
def delete_runbook(runbook_id: str, tenant_id: str = Depends(get_current_tenant)) -> dict:
    """Delete a runbook."""
    deleted = store.delete_runbook(runbook_id, tenant_id=tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Runbook not found")
    return {"deleted": True}
