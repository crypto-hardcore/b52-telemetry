from __future__ import annotations

import json
import re
from asyncio import sleep as async_sleep
from collections.abc import AsyncIterator
from secrets import compare_digest

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from b52_telemetry.authorization import (
    TELEMETRY_SESSION_COOKIE_NAME,
    TelemetryAuthorizer,
    deny_telemetry_access,
)
from b52_telemetry.contract import (
    TelemetryContractError,
    TelemetryPayload,
    validate_telemetry_payload,
)
from b52_telemetry.fleet_projection import FleetSnapshot, project_fleet
from b52_telemetry.persistence import (
    TransportCommitFailed,
    TransportOrderingRejected,
    TransportStateInvalid,
    accept_snapshot,
)
from b52_telemetry.producer_authorization import (
    ProducerAuthenticationRejected,
    authenticate_producer,
    revalidate_producer,
)
from b52_telemetry.public_projection import (
    PublicTelemetryPayload,
    project_public_telemetry,
)
from b52_telemetry.session import SessionStore
from b52_telemetry.source import (
    TelemetryFileSource,
    TelemetrySourceInvalid,
    TelemetrySourceUnavailable,
)
from b52_telemetry.source_registry import (
    B52InstanceId,
    TelemetrySourceRegistry,
    UnknownTelemetrySource,
)

TELEMETRY_STREAM_INTERVAL_SECONDS = 1.0
MAXIMUM_INGEST_BODY_BYTES = 1_048_576
MAXIMUM_TRANSPORT_SEQUENCE = 2**63 - 1
MAXIMUM_TRANSPORT_SEQUENCE_TEXT = str(MAXIMUM_TRANSPORT_SEQUENCE)
TRANSPORT_SEQUENCE_PATTERN = re.compile(r"[1-9][0-9]*")


class SessionRequest(BaseModel):
    access_key: str


def _encode_sse_payload(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"data:{serialized}\n\n"


async def _stream_telemetry(
    source: TelemetryFileSource,
    initial_payload: TelemetryPayload,
) -> AsyncIterator[str]:
    payload = initial_payload

    while True:
        yield _encode_sse_payload(payload)
        await async_sleep(TELEMETRY_STREAM_INTERVAL_SECONDS)

        try:
            payload = source.read()
        except (TelemetrySourceUnavailable, TelemetrySourceInvalid):
            return


async def _stream_fleet(
    registry: TelemetrySourceRegistry,
    initial_snapshot: FleetSnapshot,
) -> AsyncIterator[str]:
    snapshot = initial_snapshot

    while True:
        yield _encode_sse_payload(snapshot)
        await async_sleep(TELEMETRY_STREAM_INTERVAL_SECONDS)
        snapshot = project_fleet(registry)


def _resolve_source(
    registry: TelemetrySourceRegistry,
    instance_id: str,
) -> TelemetryFileSource:
    try:
        identity = B52InstanceId(instance_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail="B-52 telemetry source not found",
        ) from exc

    try:
        return registry.resolve(identity)
    except UnknownTelemetrySource as exc:
        raise HTTPException(
            status_code=404,
            detail="B-52 telemetry source not found",
        ) from exc


def _read_source(source: TelemetryFileSource) -> TelemetryPayload:
    try:
        return source.read()
    except TelemetrySourceUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="telemetry source unavailable",
        ) from exc
    except TelemetrySourceInvalid as exc:
        raise HTTPException(
            status_code=503,
            detail="telemetry source invalid",
        ) from exc


def _producer_authentication_required() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="producer authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _parse_transport_sequence(raw_sequence: str | None) -> int:
    if (
        raw_sequence is None
        or TRANSPORT_SEQUENCE_PATTERN.fullmatch(raw_sequence) is None
        or len(raw_sequence) > len(MAXIMUM_TRANSPORT_SEQUENCE_TEXT)
        or (
            len(raw_sequence) == len(MAXIMUM_TRANSPORT_SEQUENCE_TEXT)
            and raw_sequence > MAXIMUM_TRANSPORT_SEQUENCE_TEXT
        )
    ):
        raise HTTPException(status_code=400, detail="invalid transport sequence")
    return int(raw_sequence)


async def _read_ingest_body(request: Request) -> bytes:
    raw_content_length = request.headers.get("content-length")
    if raw_content_length is not None:
        try:
            content_length = int(raw_content_length)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="invalid content length"
            ) from exc
        if content_length < 0:
            raise HTTPException(status_code=400, detail="invalid content length")
        if content_length > MAXIMUM_INGEST_BODY_BYTES:
            raise HTTPException(status_code=413, detail="telemetry body too large")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAXIMUM_INGEST_BODY_BYTES:
            raise HTTPException(status_code=413, detail="telemetry body too large")
    return bytes(body)


def create_app(
    telemetry_sources: TelemetrySourceRegistry,
    telemetry_authorizer: TelemetryAuthorizer = deny_telemetry_access,
    session_store: SessionStore | None = None,
    telemetry_access_key: str | None = None,
) -> FastAPI:
    app = FastAPI()

    @app.get(
        "/api/public/instances/{instance_id}/snapshot",
        response_model=None,
    )
    def public_snapshot(instance_id: str) -> PublicTelemetryPayload:
        source = _resolve_source(telemetry_sources, instance_id)
        telemetry = _read_source(source)
        return project_public_telemetry(telemetry)

    @app.post("/api/session")
    def create_session(
        session_request: SessionRequest,
        response: Response,
    ) -> dict[str, bool]:
        if session_store is None or telemetry_access_key is None:
            raise HTTPException(
                status_code=503,
                detail="session authentication unavailable",
            )

        if not compare_digest(
            session_request.access_key,
            telemetry_access_key,
        ):
            raise HTTPException(
                status_code=401,
                detail="invalid access credential",
            )

        session_id = session_store.create()
        response.set_cookie(
            key=TELEMETRY_SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            secure=True,
            samesite="strict",
            path="/",
        )

        return {"authenticated": True}

    @app.get("/api/session")
    def session_status(request: Request) -> dict[str, bool]:
        if session_store is None:
            return {"authenticated": False}

        session_id = request.cookies.get(TELEMETRY_SESSION_COOKIE_NAME)

        return {
            "authenticated": (
                session_id is not None and session_store.contains(session_id)
            )
        }

    @app.delete("/api/session")
    def delete_session(
        request: Request,
        response: Response,
    ) -> dict[str, bool]:
        if session_store is not None:
            session_id = request.cookies.get(TELEMETRY_SESSION_COOKIE_NAME)

            if session_id is not None:
                session_store.revoke(session_id)

        response.delete_cookie(
            key=TELEMETRY_SESSION_COOKIE_NAME,
            path="/",
            secure=True,
            httponly=True,
            samesite="strict",
        )

        return {"authenticated": False}

    @app.get(
        "/api/telemetry/instances",
        dependencies=[Depends(telemetry_authorizer)],
    )
    def telemetry_instances() -> dict[str, list[str]]:
        return {
            "instances": [
                instance_id.value for instance_id in telemetry_sources.instance_ids()
            ]
        }

    @app.get(
        "/api/telemetry/fleet",
        response_model=None,
        dependencies=[Depends(telemetry_authorizer)],
    )
    def fleet_telemetry() -> FleetSnapshot:
        return project_fleet(telemetry_sources)

    @app.get(
        "/api/telemetry/fleet/stream",
        response_model=None,
        dependencies=[Depends(telemetry_authorizer)],
    )
    def stream_fleet_telemetry() -> StreamingResponse:
        initial_snapshot = project_fleet(telemetry_sources)

        return StreamingResponse(
            _stream_fleet(telemetry_sources, initial_snapshot),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
            },
        )

    @app.get(
        "/api/telemetry/instances/{instance_id}/latest",
        response_model=None,
        dependencies=[Depends(telemetry_authorizer)],
    )
    def latest_telemetry(instance_id: str) -> TelemetryPayload:
        source = _resolve_source(telemetry_sources, instance_id)
        return _read_source(source)

    @app.put(
        "/api/telemetry/instances/{instance_id}/latest",
        response_model=None,
    )
    async def ingest_latest_telemetry(
        instance_id: str,
        request: Request,
    ) -> Response:
        if request.url.scheme != "https":
            raise HTTPException(status_code=400, detail="HTTPS is required")

        try:
            authentication = authenticate_producer(
                telemetry_sources,
                instance_id,
                request.headers.get("authorization"),
            )
        except ProducerAuthenticationRejected as exc:
            raise _producer_authentication_required() from exc

        content_type = request.headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(status_code=415, detail="application/json is required")
        content_encoding = request.headers.get("content-encoding")
        if content_encoding is not None and content_encoding.lower() != "identity":
            raise HTTPException(
                status_code=415, detail="content encoding is unsupported"
            )

        sequence = _parse_transport_sequence(
            request.headers.get("x-b52-transport-sequence")
        )
        body = await _read_ingest_body(request)
        try:
            decoded = json.loads(body.decode("utf-8"))
            validate_telemetry_payload(decoded)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            TelemetryContractError,
        ) as exc:
            raise HTTPException(
                status_code=400,
                detail="invalid canonical telemetry snapshot",
            ) from exc

        registration = telemetry_sources.registration(authentication.fleet_identity)
        acceptance_lock = telemetry_sources.acceptance_lock(
            authentication.fleet_identity
        )
        with acceptance_lock:
            if not revalidate_producer(telemetry_sources, authentication):
                raise _producer_authentication_required()
            try:
                result = accept_snapshot(
                    registration.path,
                    fleet_identity=authentication.fleet_identity.value,
                    authorization_generation=(authentication.authorization_generation),
                    sequence=sequence,
                    body=body,
                )
            except TransportOrderingRejected as exc:
                raise HTTPException(
                    status_code=409,
                    detail="transport ordering rejected",
                ) from exc
            except (TransportStateInvalid, TransportCommitFailed) as exc:
                raise HTTPException(
                    status_code=503,
                    detail="transport persistence unavailable",
                ) from exc

        return Response(
            status_code=204,
            headers={
                "Cache-Control": "no-store",
                "X-B52-Transport-Result": result,
                "X-B52-Accepted-Sequence": str(sequence),
            },
        )

    @app.get(
        "/api/telemetry/instances/{instance_id}/stream",
        response_model=None,
        dependencies=[Depends(telemetry_authorizer)],
    )
    def stream_telemetry(instance_id: str) -> StreamingResponse:
        source = _resolve_source(telemetry_sources, instance_id)
        initial_payload = _read_source(source)

        return StreamingResponse(
            _stream_telemetry(source, initial_payload),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
            },
        )

    return app
