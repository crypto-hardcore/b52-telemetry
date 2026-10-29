from __future__ import annotations

import json
import os
import signal
import ssl
import sys
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from threading import Event
from typing import Callable, Final, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from b52_telemetry.app import MAXIMUM_INGEST_BODY_BYTES, MAXIMUM_TRANSPORT_SEQUENCE
from b52_telemetry.contract import TelemetryContractError, validate_telemetry_payload
from b52_telemetry.producer_authorization import TOKEN_PATTERN

RELAY_STATE_VERSION: Final = 1
POLL_INTERVAL_SECONDS: Final = 1.0
REQUEST_TIMEOUT_SECONDS: Final = 10.0
RETRY_DELAYS_SECONDS: Final = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)


class RelayError(RuntimeError):
    """Base error for telemetry relay failures."""


class RelayStateInvalid(RelayError):
    """The durable relay state is missing, corrupt, or inconsistent."""


class RelaySnapshotInvalid(RelayError):
    """The current B-52 telemetry snapshot is not deliverable."""


class RetryableDeliveryError(RelayError):
    """Delivery may be retried with the same in-memory bytes and sequence."""


class PermanentDeliveryError(RelayError):
    """Delivery requires operator correction or reprovisioning."""


@dataclass(frozen=True, slots=True)
class RelayState:
    version: int
    fleet_identity: str
    authorization_generation: int
    last_assigned_sequence: int


@dataclass(frozen=True, slots=True)
class RelayConfiguration:
    fleet_identity: str
    authorization_generation: int
    telemetry_path: Path
    state_path: Path
    receiver_url: str
    credential_path: Path


DeliverySender = Callable[[str, str, int, bytes], None]


def _strict_positive_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RelayStateInvalid(f"{field} must be a positive integer")
    return value


def read_relay_state(path: Path) -> RelayState:
    try:
        raw = path.read_text(encoding="utf-8")
        decoded = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RelayStateInvalid("relay state is unavailable or invalid") from exc
    if not isinstance(decoded, dict) or set(decoded) != {
        "version",
        "fleet_identity",
        "authorization_generation",
        "last_assigned_sequence",
    }:
        raise RelayStateInvalid("relay state fields are invalid")
    value = cast(dict[str, object], decoded)
    if value["version"] != RELAY_STATE_VERSION:
        raise RelayStateInvalid("relay state version is invalid")
    identity = value["fleet_identity"]
    if not isinstance(identity, str) or not identity:
        raise RelayStateInvalid("relay fleet identity is invalid")
    last_sequence = value["last_assigned_sequence"]
    if (
        isinstance(last_sequence, bool)
        or not isinstance(last_sequence, int)
        or not 0 <= last_sequence <= MAXIMUM_TRANSPORT_SEQUENCE
    ):
        raise RelayStateInvalid("last assigned sequence is invalid")
    return RelayState(
        version=RELAY_STATE_VERSION,
        fleet_identity=identity,
        authorization_generation=_strict_positive_integer(
            value["authorization_generation"],
            field="authorization_generation",
        ),
        last_assigned_sequence=last_sequence,
    )


def _read_configured_relay_state(configuration: RelayConfiguration) -> RelayState:
    state = read_relay_state(configuration.state_path)
    if (
        state.fleet_identity != configuration.fleet_identity
        or state.authorization_generation != configuration.authorization_generation
    ):
        raise RelayStateInvalid("relay state does not match configuration")
    return state


def write_relay_state(path: Path, state: RelayState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary_path = path.with_name(f".{path.name}.tmp")
    payload = json.dumps(
        asdict(state),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    descriptor = -1
    try:
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary_path, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise RelayStateInvalid("could not persist relay state") from exc


def initialize_relay_state(
    path: Path,
    *,
    fleet_identity: str,
    authorization_generation: int,
) -> None:
    if path.exists():
        raise RelayStateInvalid("relay state already exists")
    write_relay_state(
        path,
        RelayState(
            version=RELAY_STATE_VERSION,
            fleet_identity=fleet_identity,
            authorization_generation=authorization_generation,
            last_assigned_sequence=0,
        ),
    )


def reset_relay_state(
    path: Path,
    *,
    fleet_identity: str,
    previous_generation: int,
    authorization_generation: int,
) -> None:
    if authorization_generation != previous_generation + 1:
        raise RelayStateInvalid("authorization generation must increment by one")
    current = read_relay_state(path)
    if (
        current.fleet_identity != fleet_identity
        or current.authorization_generation != previous_generation
    ):
        raise RelayStateInvalid("relay state does not match the requested reset")
    write_relay_state(
        path,
        RelayState(
            version=RELAY_STATE_VERSION,
            fleet_identity=fleet_identity,
            authorization_generation=authorization_generation,
            last_assigned_sequence=0,
        ),
    )


def rotate_relay_generation(
    path: Path,
    *,
    fleet_identity: str,
    previous_generation: int,
    authorization_generation: int,
) -> None:
    if authorization_generation != previous_generation + 1:
        raise RelayStateInvalid("authorization generation must increment by one")
    current = read_relay_state(path)
    if (
        current.fleet_identity != fleet_identity
        or current.authorization_generation != previous_generation
    ):
        raise RelayStateInvalid("relay state does not match the requested rotation")
    write_relay_state(
        path,
        RelayState(
            version=RELAY_STATE_VERSION,
            fleet_identity=fleet_identity,
            authorization_generation=authorization_generation,
            last_assigned_sequence=current.last_assigned_sequence,
        ),
    )


def read_canonical_snapshot(path: Path) -> bytes:
    try:
        body = path.read_bytes()
    except OSError as exc:
        raise RelaySnapshotInvalid(
            "canonical telemetry snapshot is unavailable"
        ) from exc
    if len(body) > MAXIMUM_INGEST_BODY_BYTES:
        raise RelaySnapshotInvalid(
            "canonical telemetry snapshot exceeds transport limit"
        )
    try:
        decoded = json.loads(body.decode("utf-8"))
        validate_telemetry_payload(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, TelemetryContractError) as exc:
        raise RelaySnapshotInvalid("canonical telemetry snapshot is invalid") from exc
    return body


def send_https(receiver_url: str, token: str, sequence: int, body: bytes) -> None:
    request = Request(
        receiver_url,
        data=body,
        method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-B52-Transport-Sequence": str(sequence),
        },
    )
    try:
        with urlopen(  # noqa: S310 -- configuration enforces an HTTPS URL.
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
            context=ssl.create_default_context(),
        ) as response:
            status = response.status
            result = response.headers.get("X-B52-Transport-Result")
            accepted_sequence = response.headers.get("X-B52-Accepted-Sequence")
    except HTTPError as exc:
        if exc.code == 429 or 500 <= exc.code <= 599:
            raise RetryableDeliveryError(
                "receiver temporarily rejected delivery"
            ) from exc
        raise PermanentDeliveryError("receiver rejected telemetry delivery") from exc
    except (TimeoutError, URLError, OSError) as exc:
        raise RetryableDeliveryError("receiver is unavailable") from exc
    if (
        status != 204
        or result not in {"accepted", "duplicate"}
        or accepted_sequence != str(sequence)
    ):
        raise PermanentDeliveryError("receiver returned an invalid success response")


class TelemetryRelay:
    def __init__(
        self,
        configuration: RelayConfiguration,
        token: str,
        *,
        sender: DeliverySender = send_https,
        stop_event: Event | None = None,
    ) -> None:
        if not configuration.receiver_url.startswith("https://"):
            raise RelayError("receiver URL must use HTTPS")
        if TOKEN_PATTERN.fullmatch(token) is None:
            raise RelayError("producer credential is invalid")
        _read_configured_relay_state(configuration)
        self._configuration = configuration
        self._token = token
        self._sender = sender
        self._stop = stop_event if stop_event is not None else Event()
        self._last_delivered_digest: str | None = None

    def stop(self) -> None:
        self._stop.set()

    def deliver_current_if_changed(self) -> bool:
        body = read_canonical_snapshot(self._configuration.telemetry_path)
        digest = sha256(body).hexdigest()
        if digest == self._last_delivered_digest:
            return False

        state = _read_configured_relay_state(self._configuration)
        if state.last_assigned_sequence >= MAXIMUM_TRANSPORT_SEQUENCE:
            raise RelayStateInvalid("transport sequence is exhausted")
        sequence = state.last_assigned_sequence + 1
        write_relay_state(
            self._configuration.state_path,
            RelayState(
                version=RELAY_STATE_VERSION,
                fleet_identity=state.fleet_identity,
                authorization_generation=state.authorization_generation,
                last_assigned_sequence=sequence,
            ),
        )

        attempt = 0
        while not self._stop.is_set():
            try:
                self._sender(
                    self._configuration.receiver_url,
                    self._token,
                    sequence,
                    body,
                )
                self._last_delivered_digest = digest
                return True
            except RetryableDeliveryError:
                delay = RETRY_DELAYS_SECONDS[
                    min(attempt, len(RETRY_DELAYS_SECONDS) - 1)
                ]
                attempt += 1
                self._stop.wait(delay)
        return False

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.deliver_current_if_changed()
            except RelaySnapshotInvalid:
                pass
            self._stop.wait(POLL_INTERVAL_SECONDS)


def configuration_from_environment() -> RelayConfiguration:
    def required(name: str) -> str:
        value = os.environ.get(name)
        if value is None or not value.strip():
            raise RelayError(f"{name} must be configured")
        return value

    generation_text = required("B52_RELAY_AUTHORIZATION_GENERATION")
    try:
        generation = int(generation_text)
    except ValueError as exc:
        raise RelayError("relay authorization generation is invalid") from exc
    if generation < 1:
        raise RelayError("relay authorization generation is invalid")

    identity = required("B52_RELAY_INSTANCE_ID")
    endpoint = required("B52_RELAY_RECEIVER_URL").rstrip("/")
    credentials_directory = required("CREDENTIALS_DIRECTORY")
    return RelayConfiguration(
        fleet_identity=identity,
        authorization_generation=generation,
        telemetry_path=Path(required("B52_RELAY_TELEMETRY_PATH")),
        state_path=Path(required("B52_RELAY_STATE_PATH")),
        receiver_url=f"{endpoint}/api/telemetry/instances/{identity}/latest",
        credential_path=Path(credentials_directory) / "producer.token",
    )


def main() -> None:
    try:
        configuration = configuration_from_environment()
        token = configuration.credential_path.read_text(encoding="utf-8").strip()
        relay = TelemetryRelay(configuration, token)
        signal.signal(signal.SIGTERM, lambda _signum, _frame: relay.stop())
        signal.signal(signal.SIGINT, lambda _signum, _frame: relay.stop())
        relay.run()
    except OSError:
        print("telemetry relay credential is unavailable", file=sys.stderr)
        raise SystemExit(78) from None
    except (PermanentDeliveryError, RelayError) as exc:
        print(f"telemetry relay stopped: {exc}", file=sys.stderr)
        raise SystemExit(78) from None


if __name__ == "__main__":
    main()
