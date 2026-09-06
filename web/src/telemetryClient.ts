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

export async function fetchLatestTelemetry(): Promise<TelemetryPayload> {
  const response = await fetch("/api/telemetry/latest");

  if (!response.ok) {
    throw new Error(`telemetry request failed with status ${response.status}`);
  }

  return requireTelemetryObject(await response.json());
}

export function subscribeTelemetry(
  onTelemetry: (payload: TelemetryPayload) => void,
  onError: () => void,
): TelemetrySubscription {
  const source = new EventSource("/api/telemetry/stream");

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
