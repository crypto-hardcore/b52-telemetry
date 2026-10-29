from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from secrets import compare_digest

from b52_telemetry.source_registry import (
    B52InstanceId,
    TelemetrySourceRegistry,
    UnknownTelemetrySource,
)

TOKEN_PATTERN = re.compile(r"b52r_v1_[A-Za-z0-9_-]{43}")
DUMMY_DIGEST = "0" * 64


class ProducerAuthenticationRejected(RuntimeError):
    """A deliberately uniform producer-authentication failure."""


@dataclass(frozen=True, slots=True)
class ProducerAuthenticationContext:
    fleet_identity: B52InstanceId
    authorization_generation: int
    credential_sha256: str


def credential_digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def authenticate_producer(
    registry: TelemetrySourceRegistry,
    raw_instance_id: str,
    authorization_header: str | None,
) -> ProducerAuthenticationContext:
    supplied_token = ""
    if authorization_header is not None:
        scheme, separator, candidate = authorization_header.partition(" ")
        if scheme == "Bearer" and separator and candidate and " " not in candidate:
            supplied_token = candidate

    supplied_digest = credential_digest(supplied_token)
    try:
        instance_id = B52InstanceId(raw_instance_id)
        registration = registry.registration(instance_id)
    except (ValueError, UnknownTelemetrySource):
        compare_digest(supplied_digest, DUMMY_DIGEST)
        raise ProducerAuthenticationRejected from None

    authorization = registration.producer
    digest_matches = compare_digest(
        supplied_digest,
        authorization.credential_sha256,
    )
    token_is_well_formed = TOKEN_PATTERN.fullmatch(supplied_token) is not None
    if not authorization.enabled or not token_is_well_formed or not digest_matches:
        raise ProducerAuthenticationRejected

    return ProducerAuthenticationContext(
        fleet_identity=instance_id,
        authorization_generation=authorization.authorization_generation,
        credential_sha256=authorization.credential_sha256,
    )


def revalidate_producer(
    registry: TelemetrySourceRegistry,
    context: ProducerAuthenticationContext,
) -> bool:
    try:
        authorization = registry.registration(context.fleet_identity).producer
    except UnknownTelemetrySource:
        return False
    return (
        authorization.enabled
        and authorization.authorization_generation == context.authorization_generation
        and compare_digest(
            authorization.credential_sha256,
            context.credential_sha256,
        )
    )
