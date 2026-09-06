type SessionStatus = {
  authenticated: boolean;
};

function requireSessionStatus(value: unknown): SessionStatus {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    !("authenticated" in value) ||
    typeof value.authenticated !== "boolean"
  ) {
    throw new Error("session response must contain authenticated boolean");
  }

  return {
    authenticated: value.authenticated,
  };
}

async function requireSuccessfulSessionResponse(
  response: Response,
): Promise<SessionStatus> {
  if (!response.ok) {
    throw new Error(`session request failed with status ${response.status}`);
  }

  return requireSessionStatus(await response.json());
}

export async function fetchSessionStatus(): Promise<SessionStatus> {
  return requireSuccessfulSessionResponse(await fetch("/api/session"));
}

export async function createSession(accessKey: string): Promise<SessionStatus> {
  return requireSuccessfulSessionResponse(
    await fetch("/api/session", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        access_key: accessKey,
      }),
    }),
  );
}

export async function deleteSession(): Promise<SessionStatus> {
  return requireSuccessfulSessionResponse(
    await fetch("/api/session", {
      method: "DELETE",
    }),
  );
}
