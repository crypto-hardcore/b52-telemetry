export type TelemetryPayload = Record<string, unknown>;

export type TelemetrySubscription = {
  close: () => void;
};

function requireTelemetryObject(value: unknown): TelemetryPayload {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("telemetry payload must be a JSON object");
  }

  return value as TelemetryPayload;
}

function requireTelemetryInstances(value: unknown): string[] {
  const payload = requireTelemetryObject(value);
  const instances = payload.instances;

  if (
    !Array.isArray(instances) ||
    instances.some(
      (instanceId) =>
        typeof instanceId !== "string" ||
        instanceId.length === 0 ||
        instanceId.trim() !== instanceId,
    )
  ) {
    throw new Error("telemetry instances response is invalid");
  }

  return instances;
}

export async function fetchTelemetryInstances(): Promise<string[]> {
  const response = await fetch("/api/telemetry/instances");

  if (!response.ok) {
    throw new Error(
      `telemetry instances request failed with status ${response.status}`,
    );
  }

  return requireTelemetryInstances(await response.json());
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
