from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Response

from app.user_collection.models import (
    CollectionItem,
    CollectionItemCreate,
    CollectionItemPatch,
    CollectionListResponse,
)

router = APIRouter(prefix="/api/user-collection", tags=["user-collection"])

_store: dict[UUID, CollectionItem] = {}


def _require_subject(x_auth_subject: Annotated[str, Header()]) -> str:
    return x_auth_subject


@router.post("/items", response_model=CollectionItem, status_code=201)
def create_item(
    body: CollectionItemCreate,
    x_auth_subject: Annotated[str, Header()],
) -> CollectionItem:
    now = datetime.now(tz=timezone.utc)
    item = CollectionItem(
        id=uuid4(),
        user_auth_subject=x_auth_subject,
        created_at=now,
        updated_at=now,
        **body.model_dump(),
    )
    _store[item.id] = item
    return item


@router.get("/items", response_model=CollectionListResponse)
def list_items(
    x_auth_subject: Annotated[str, Header()],
) -> CollectionListResponse:
    user_items = [i for i in _store.values() if i.user_auth_subject == x_auth_subject]
    return CollectionListResponse(items=user_items, total=len(user_items))


@router.get("/items/{item_id}", response_model=CollectionItem)
def get_item(
    item_id: UUID,
    x_auth_subject: Annotated[str, Header()],
) -> CollectionItem:
    item = _store.get(item_id)
    if item is None or item.user_auth_subject != x_auth_subject:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.patch("/items/{item_id}", response_model=CollectionItem)
def patch_item(
    item_id: UUID,
    body: CollectionItemPatch,
    x_auth_subject: Annotated[str, Header()],
) -> CollectionItem:
    item = _store.get(item_id)
    if item is None or item.user_auth_subject != x_auth_subject:
        raise HTTPException(status_code=404, detail="Item not found")
    updated_data = item.model_dump()
    patch_data = body.model_dump(exclude_unset=True)
    updated_data.update(patch_data)
    updated_data["updated_at"] = datetime.now(tz=timezone.utc)
    new_item = CollectionItem(**updated_data)
    _store[item_id] = new_item
    return new_item


@router.delete("/items/{item_id}", status_code=204, response_class=Response)
def delete_item(
    item_id: UUID,
    x_auth_subject: Annotated[str, Header()],
) -> Response:
    item = _store.get(item_id)
    if item is None or item.user_auth_subject != x_auth_subject:
        raise HTTPException(status_code=404, detail="Item not found")
    del _store[item_id]
    return Response(status_code=204)
