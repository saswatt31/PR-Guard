"""HTTP surface for GitHub webhooks."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.settings import Settings
from app.webhooks.handler import InvalidPayloadError, process_event
from app.webhooks.signature import verify_signature

logger = logging.getLogger(__name__)

router = APIRouter()


async def _read_limited_body(request: Request, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail="webhook payload too large")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/webhooks/github", status_code=202, tags=["webhooks"])
async def github_webhook(request: Request):
    settings: Settings = request.app.state.settings
    body = await _read_limited_body(request, settings.max_webhook_bytes)
    signature = request.headers.get("x-hub-signature-256")

    if not verify_signature(body, signature, settings.github_webhook_secret):
        logger.warning("rejected webhook with invalid signature")
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    event = request.headers.get("x-github-event")
    delivery_id = request.headers.get("x-github-delivery")
    if not event or not delivery_id:
        raise HTTPException(status_code=400, detail="missing GitHub event headers")

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid JSON payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    try:
        outcome = await run_in_threadpool(
            process_event,
            request.app.state.db,
            settings,
            event=event,
            payload=payload,
            payload_bytes=body,
            delivery_id=delivery_id,
        )
    except InvalidPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("webhook event=%s delivery=%s status=%s", event, delivery_id, outcome.status)
    content: dict[str, str] = {"status": outcome.status}
    if outcome.run_id:
        content["run_id"] = outcome.run_id
    if outcome.reason:
        content["reason"] = outcome.reason
    return JSONResponse(status_code=200 if outcome.status == "pong" else 202, content=content)
