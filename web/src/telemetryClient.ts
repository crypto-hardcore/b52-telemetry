export type TelemetryPayload = Record<string, unknown>;

export type FleetSourceState = "AVAILABLE" | "UNAVAILABLE" | "INVALID";

export type FleetMember = {
  instance_id: string;
  source_state: FleetSourceState;
  telemetry: TelemetryPayload | null;
};

export type FleetSnapshot = {
  instances: FleetMember[];
};

export type TelemetrySubscription = {
  close: () => void;
};

function requireTelemetryObject(value: unknown): TelemetryPayload {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("telemetry payload must be a JSON object");
  }

  return value as TelemetryPayload;
}

function requireFleetSourceState(value: unknown): FleetSourceState {
  if (
    value !== "AVAILABLE" &&
    value !== "UNAVAILABLE" &&
    value !== "INVALID"
  ) {
    throw new Error("fleet member source state is invalid");
  }

  return value;
}

function requireFleetMember(value: unknown): FleetMember {
  const member = requireTelemetryObject(value);
  const instanceId = member.instance_id;

  if (
    typeof instanceId !== "string" ||
    instanceId.length === 0 ||
    instanceId.trim() !== instanceId
  ) {
    throw new Error("fleet member instance id is invalid");
  }

  const sourceState = requireFleetSourceState(member.source_state);

  if (sourceState === "AVAILABLE") {
    return {
      instance_id: instanceId,
      source_state: sourceState,
      telemetry: requireTelemetryObject(member.telemetry),
    };
  }

  if (member.telemetry !== null) {
    throw new Error("unavailable fleet member telemetry must be null");
  }

  return {
    instance_id: instanceId,
    source_state: sourceState,
    telemetry: null,
  };
}

function requireFleetSnapshot(value: unknown): FleetSnapshot {
  const payload = requireTelemetryObject(value);

  if (!Array.isArray(payload.instances)) {
    throw new Error("fleet telemetry response is invalid");
  }

  return {
    instances: payload.instances.map(requireFleetMember),
  };
}

export async function fetchFleetTelemetry(): Promise<FleetSnapshot> {
  const response = await fetch("/api/telemetry/fleet");

  if (!response.ok) {
    throw new Error(
      `fleet telemetry request failed with status ${response.status}`,
    );
  }

  return requireFleetSnapshot(await response.json());
}

export function subscribeFleetTelemetry(
  onFleet: (snapshot: FleetSnapshot) => void,
  onError: () => void,
): TelemetrySubscription {
  const source = new EventSource("/api/telemetry/fleet/stream");

  source.onmessage = (event) => {
    try {
      const snapshot = requireFleetSnapshot(JSON.parse(event.data));
      onFleet(snapshot);
    } catch {
      onError();
    }
  };

  source.onerror = () => {
    onError();
  };

  return {
    close: () => {
      source.close();
    },
  };
}

function telemetryInstancePath(instanceId: string): string {
  if (instanceId.length === 0 || instanceId.trim() !== instanceId) {
    throw new Error(
      "B-52 instance id must be non-empty and contain no surrounding whitespace",
    );
  }

  return `/api/telemetry/instances/${encodeURIComponent(instanceId)}`;
}

export async function fetchLatestTelemetry(
  instanceId: string,
): Promise<TelemetryPayload> {
  const response = await fetch(`${telemetryInstancePath(instanceId)}/latest`);

  if (!response.ok) {
    throw new Error(`telemetry request failed with status ${response.status}`);
  }

  return requireTelemetryObject(await response.json());
}

export function subscribeTelemetry(
  instanceId: string,
  onTelemetry: (payload: TelemetryPayload) => void,
  onError: () => void,
): TelemetrySubscription {
  const source = new EventSource(
    `${telemetryInstancePath(instanceId)}/stream`,
  );

  source.onmessage = (event) => {
    try {
      const payload = requireTelemetryObject(JSON.parse(event.data));
      onTelemetry(payload);
    } catch {
      onError();
    }
  };

  source.onerror = () => {
    onError();
  };

  return {
    close: () => {
      source.close();
    },
  };
}
