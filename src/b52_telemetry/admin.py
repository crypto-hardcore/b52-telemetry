from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from b52_telemetry.persistence import (
    establish_baseline,
    reset_ordering_baseline,
    update_current_authorization_generation,
)
from b52_telemetry.relay import (
    initialize_relay_state,
    reset_relay_state,
    rotate_relay_generation,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="B-52 telemetry transport administration"
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)

    def common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--instance", required=True)
        subparser.add_argument("--generation", required=True, type=int)

    baseline = subparsers.add_parser("receiver-baseline")
    common(baseline)
    baseline.add_argument("--snapshot", required=True, type=Path)

    generation = subparsers.add_parser("receiver-generation")
    common(generation)
    generation.add_argument("--previous-generation", required=True, type=int)
    generation.add_argument("--snapshot", required=True, type=Path)

    reset = subparsers.add_parser("receiver-reset")
    common(reset)
    reset.add_argument("--previous-generation", required=True, type=int)
    reset.add_argument("--snapshot", required=True, type=Path)

    relay_initialize = subparsers.add_parser("relay-initialize")
    common(relay_initialize)
    relay_initialize.add_argument("--state", required=True, type=Path)

    relay_rotate = subparsers.add_parser("relay-rotate")
    common(relay_rotate)
    relay_rotate.add_argument("--previous-generation", required=True, type=int)
    relay_rotate.add_argument("--state", required=True, type=Path)

    relay_reset = subparsers.add_parser("relay-reset")
    common(relay_reset)
    relay_reset.add_argument("--previous-generation", required=True, type=int)
    relay_reset.add_argument("--state", required=True, type=Path)
    return parser


def main(arguments: Sequence[str] | None = None) -> None:
    values = _parser().parse_args(arguments)
    if values.operation == "receiver-baseline":
        establish_baseline(
            values.snapshot,
            fleet_identity=values.instance,
            authorization_generation=values.generation,
        )
    elif values.operation == "receiver-generation":
        update_current_authorization_generation(
            values.snapshot,
            fleet_identity=values.instance,
            previous_generation=values.previous_generation,
            authorization_generation=values.generation,
        )
    elif values.operation == "receiver-reset":
        reset_ordering_baseline(
            values.snapshot,
            fleet_identity=values.instance,
            previous_generation=values.previous_generation,
            authorization_generation=values.generation,
        )
    elif values.operation == "relay-initialize":
        initialize_relay_state(
            values.state,
            fleet_identity=values.instance,
            authorization_generation=values.generation,
        )
    elif values.operation == "relay-rotate":
        rotate_relay_generation(
            values.state,
            fleet_identity=values.instance,
            previous_generation=values.previous_generation,
            authorization_generation=values.generation,
        )
    elif values.operation == "relay-reset":
        reset_relay_state(
            values.state,
            fleet_identity=values.instance,
            previous_generation=values.previous_generation,
            authorization_generation=values.generation,
        )


if __name__ == "__main__":
    main()
