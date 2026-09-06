import { type FormEvent, useEffect, useState } from "react";

import "./App.css";
import {
  createSession,
  deleteSession,
  fetchSessionStatus,
} from "./sessionClient";
import {
  fetchLatestTelemetry,
  subscribeTelemetry,
  type TelemetryPayload,
  type TelemetrySubscription,
} from "./telemetryClient";

type JsonObject = Record<string, unknown>;

type ConnectionState = "CONNECTING" | "LIVE" | "INTERRUPTED";

function asObject(value: unknown): JsonObject | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }

  return value as JsonObject;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }

  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return String(value);
  }

  return "—";
}

function Field({
  label,
  value,
}: {
  label: string;
  value: unknown;
}) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <span className="field-value">{displayValue(value)}</span>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function EmptySection() {
  return <p className="empty">Not present in canonical snapshot.</p>;
}

function HealthFact({
  label,
  value,
}: {
  label: string;
  value: unknown;
}) {
  const fact = asObject(value);

  if (fact === null) {
    return (
      <div className="health-row">
        <span>{label}</span>
        <span>—</span>
        <span>—</span>
      </div>
    );
  }

  return (
    <div className="health-row">
      <span>{label}</span>
      <span>{displayValue(fact.state)}</span>
      <span>{displayValue(fact.observed_at)}</span>
    </div>
  );
}

function Orders({ value }: { value: unknown }) {
  const orders = asArray(value)
    .map(asObject)
    .filter((order): order is JsonObject => order !== null);

  if (orders.length === 0) {
    return <p className="empty">No orders in canonical snapshot.</p>;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>LEVEL</th>
            <th>ORDER ID</th>
            <th>CLIENT ORDER ID</th>
            <th>STATE</th>
            <th>PRICE</th>
            <th>ORIGINAL QTY</th>
            <th>EXECUTED QTY</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order, index) => (
            <tr key={`${displayValue(order.order_id)}-${index}`}>
              <td>{displayValue(order.grid_level)}</td>
              <td>{displayValue(order.order_id)}</td>
              <td>{displayValue(order.client_order_id)}</td>
              <td>{displayValue(order.state)}</td>
              <td>{displayValue(order.price)}</td>
              <td>{displayValue(order.original_quantity)}</td>
              <td>{displayValue(order.executed_quantity)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SystemPanel({ value }: { value: unknown }) {
  const system = asObject(value);

  return (
    <Section title="SYSTEM">
      {system === null ? (
        <EmptySection />
      ) : (
        <div className="health-table">
          <div className="health-row health-header">
            <span>COMPONENT</span>
            <span>STATE</span>
            <span>OBSERVED AT</span>
          </div>
          <HealthFact label="HTTPS" value={system.https} />
          <HealthFact label="WEBSOCKET" value={system.websocket} />
          <HealthFact label="AUTHENTICATION" value={system.authentication} />
          <HealthFact label="STREAM FRESHNESS" value={system.stream_freshness} />
          <HealthFact
            label="EVIDENCE CONTINUITY"
            value={system.evidence_continuity}
          />
          <HealthFact label="SQLITE" value={system.sqlite} />
          <HealthFact label="RECONCILIATION" value={system.reconciliation} />
        </div>
      )}
    </Section>
  );
}

function MarketPanel({ value }: { value: unknown }) {
  const market = asObject(value);

  return (
    <Section title="MARKET">
      {market === null ? (
        <EmptySection />
      ) : (
        <div className="field-grid">
          <Field label="SYMBOL" value={market.symbol} />
          <Field label="PRICE" value={market.price} />
          <Field label="OBSERVED AT" value={market.observed_at} />
        </div>
      )}
    </Section>
  );
}

function LifecyclePanel({ value }: { value: unknown }) {
  const lifecycle = asObject(value);

  if (lifecycle === null) {
    return <EmptySection />;
  }

  return (
    <div className="field-grid">
      <Field label="LIFECYCLE ID" value={lifecycle.lifecycle_id} />
      <Field label="SYMBOL" value={lifecycle.symbol} />
      <Field label="STATE" value={lifecycle.state} />
      <Field
        label="BEGINNING WALLET BALANCE"
        value={lifecycle.beginning_wallet_balance}
      />
      <Field label="CREATED AT" value={lifecycle.created_at} />
      <Field label="CLOSED AT" value={lifecycle.closed_at} />
      <Field label="SL COMMITTED AT" value={lifecycle.sl_committed_at} />
      <Field label="SL EXECUTED AT" value={lifecycle.sl_executed_at} />
    </div>
  );
}

function TradeStatusPanel({ value }: { value: unknown }) {
  const status = asObject(value);

  if (status === null) {
    return <EmptySection />;
  }

  return (
    <div className="field-grid">
      <Field label="GROUP" value={status.group} />
      <Field label="LIFECYCLE STATUS" value={status.lifecycle_status} />
      <Field label="FINAL PNL STATUS" value={status.final_pnl_status} />
    </div>
  );
}

function EntryPanel({ value }: { value: unknown }) {
  const entry = asObject(value);

  if (entry === null) {
    return <EmptySection />;
  }

  return (
    <>
      <div className="field-grid">
        <Field label="STATE" value={entry.state} />
        <Field label="SIDE" value={entry.side} />
        <Field label="TOTAL GRID STEPS" value={entry.total_grid_steps} />
        <Field label="POSITION SIZE" value={entry.position_size} />
        <Field label="POSITION FILLED" value={entry.position_filled} />
        <Field
          label="DYNAMIC ENTRY ZONE LOW"
          value={entry.dynamic_entry_zone_low}
        />
        <Field
          label="DYNAMIC ENTRY ZONE HIGH"
          value={entry.dynamic_entry_zone_high}
        />
        <Field
          label="RECONCILIATION STATUS"
          value={entry.reconciliation_status}
        />
        <Field label="OBSERVED AT" value={entry.observed_at} />
      </div>
      <h3>ENTRY ORDERS</h3>
      <Orders value={entry.orders} />
    </>
  );
}

function PositionPanel({ value }: { value: unknown }) {
  const position = asObject(value);

  if (position === null) {
    return <EmptySection />;
  }

  return (
    <div className="field-grid">
      <Field label="STATE" value={position.state} />
      <Field label="SIDE" value={position.side} />
      <Field label="QUANTITY" value={position.quantity} />
      <Field
        label="AVERAGE ENTRY PRICE"
        value={position.average_entry_price}
      />
      <Field label="BREAK EVEN PRICE" value={position.break_even_price} />
      <Field label="LIQUIDATION PRICE" value={position.liquidation_price} />
      <Field
        label="RECONCILIATION STATUS"
        value={position.reconciliation_status}
      />
      <Field label="OBSERVED AT" value={position.observed_at} />
    </div>
  );
}

function ExitPanel({ value }: { value: unknown }) {
  const exit = asObject(value);

  if (exit === null) {
    return <EmptySection />;
  }

  return (
    <>
      <div className="field-grid">
        <Field label="STATE" value={exit.state} />
        <Field label="SIDE" value={exit.side} />
        <Field label="TOTAL GRID STEPS" value={exit.total_grid_steps} />
        <Field label="POSITION SIZE" value={exit.position_size} />
        <Field
          label="CLOSED POSITION SIZE"
          value={exit.closed_position_size}
        />
        <Field
          label="COVERED POSITION SIZE"
          value={exit.covered_position_size}
        />
        <Field
          label="DYNAMIC EXIT ZONE LOW"
          value={exit.dynamic_exit_zone_low}
        />
        <Field
          label="DYNAMIC EXIT ZONE HIGH"
          value={exit.dynamic_exit_zone_high}
        />
        <Field
          label="RECONCILIATION STATUS"
          value={exit.reconciliation_status}
        />
        <Field label="OBSERVED AT" value={exit.observed_at} />
      </div>
      <h3>EXIT ORDERS</h3>
      <Orders value={exit.orders} />
    </>
  );
}

function RiskPanel({ value }: { value: unknown }) {
  const risk = asObject(value);

  if (risk === null) {
    return <EmptySection />;
  }

  return (
    <div className="field-grid">
      <Field label="UNREALIZED PNL" value={risk.unrealized_pnl} />
      <Field label="GATE 1 RISK RATIO" value={risk.gate_1_risk_ratio} />
      <Field label="GATE 2 RISK RATIO" value={risk.gate_2_risk_ratio} />
      <Field
        label="GATE 1 HEALTH %"
        value={risk.gate_1_health_percentage}
      />
      <Field
        label="GATE 2 HEALTH %"
        value={risk.gate_2_health_percentage}
      />
      <Field
        label="GOVERNING HEALTH %"
        value={risk.governing_health_percentage}
      />
      <Field label="HEALTH" value={risk.health} />
      <Field
        label="STOP LOSS COMMIT REQUIRED"
        value={risk.stop_loss_commit_required}
      />
    </div>
  );
}

function MissionPanel({ value }: { value: unknown }) {
  const mission = asObject(value);

  if (mission === null) {
    return (
      <Section title="MISSION">
        <EmptySection />
      </Section>
    );
  }

  return (
    <>
      <Section title="LIFECYCLE">
        <LifecyclePanel value={mission.lifecycle} />
      </Section>

      <Section title="TRADE STATUS">
        <TradeStatusPanel value={mission.trade_status} />
      </Section>

      <Section title="ENTRY">
        <EntryPanel value={mission.entry} />
      </Section>

      <Section title="POSITION">
        <PositionPanel value={mission.position} />
      </Section>

      <Section title="EXIT">
        <ExitPanel value={mission.exit} />
      </Section>

      <Section title="RISK">
        <RiskPanel value={mission.risk} />
      </Section>
    </>
  );
}

type AuthenticationState =
  | "CHECKING"
  | "UNAUTHENTICATED"
  | "AUTHENTICATED";

function AccessScreen({
  sessionError,
  onAuthenticated,
}: {
  sessionError: string | null;
  onAuthenticated: () => void;
}) {
  const [accessKey, setAccessKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [authenticationError, setAuthenticationError] =
    useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (submitting) {
      return;
    }

    setSubmitting(true);
    setAuthenticationError(null);

    try {
      const session = await createSession(accessKey);

      if (!session.authenticated) {
        throw new Error("session was not established");
      }

      setAccessKey("");
      onAuthenticated();
    } catch {
      setAuthenticationError(
        "Access denied or authentication service unavailable.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="access-page">
      <section className="access-panel">
        <p className="eyebrow">B-52 OBSERVATION SURFACE</p>
        <h1>B-52 TELEMETRY</h1>
        <p className="subtitle">
          Restricted read-only canonical runtime telemetry.
        </p>

        <form className="access-form" onSubmit={submit}>
          <label htmlFor="telemetry-access-key">ACCESS KEY</label>
          <input
            id="telemetry-access-key"
            type="password"
            value={accessKey}
            onChange={(event) => setAccessKey(event.target.value)}
            autoComplete="current-password"
            disabled={submitting}
          />

          <button type="submit" disabled={submitting || accessKey.length === 0}>
            {submitting ? "AUTHENTICATING" : "ENTER TELEMETRY"}
          </button>
        </form>

        {authenticationError === null ? null : (
          <p className="access-error" role="alert">
            {authenticationError}
          </p>
        )}

        {sessionError === null ? null : (
          <p className="access-error" role="alert">
            {sessionError}
          </p>
        )}
      </section>
    </main>
  );
}

function SessionCheckingScreen() {
  return (
    <main className="access-page">
      <section className="access-panel">
        <p className="eyebrow">B-52 OBSERVATION SURFACE</p>
        <h1>B-52 TELEMETRY</h1>
        <p className="subtitle">Verifying observation access.</p>
      </section>
    </main>
  );
}

function TelemetrySurface({ onLogout }: { onLogout: () => void }) {
  const [telemetry, setTelemetry] = useState<TelemetryPayload | null>(null);
  const [connection, setConnection] =
    useState<ConnectionState>("CONNECTING");

  useEffect(() => {
    let active = true;
    let streamReceived = false;
    let subscription: TelemetrySubscription | null = null;

    void fetchLatestTelemetry()
      .then((payload) => {
        if (active && !streamReceived) {
          setTelemetry(payload);
        }
      })
      .catch(() => {
        if (active) {
          setConnection("INTERRUPTED");
        }
      });

    subscription = subscribeTelemetry(
      (payload) => {
        if (!active) {
          return;
        }

        streamReceived = true;
        setTelemetry(payload);
        setConnection("LIVE");
      },
      () => {
        if (active) {
          setConnection("INTERRUPTED");
        }
      },
    );

    return () => {
      active = false;
      subscription?.close();
    };
  }, []);

  const system = telemetry === null ? null : telemetry.system;
  const market = telemetry === null ? null : telemetry.market;
  const mission = telemetry === null ? null : telemetry.mission;

  return (
    <main className="telemetry-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">B-52 OBSERVATION SURFACE</p>
          <h1>B-52 TELEMETRY</h1>
          <p className="subtitle">Read-only canonical runtime telemetry.</p>
        </div>

        <div className="header-actions">
          <div className="connection-block">
            <span className="connection-label">WEBSITE CONNECTION</span>
            <strong>{connection}</strong>
          </div>

          <button className="logout-button" type="button" onClick={onLogout}>
            END SESSION
          </button>
        </div>
      </header>

      {telemetry === null ? (
        <section className="panel">
          <p className="empty">No canonical telemetry snapshot available.</p>
        </section>
      ) : (
        <>
          <section className="snapshot-meta">
            <Field label="SCHEMA VERSION" value={telemetry.schema_version} />
            <Field label="GENERATED AT" value={telemetry.generated_at} />
          </section>

          <SystemPanel value={system} />
          <MarketPanel value={market} />
          <MissionPanel value={mission} />
        </>
      )}
    </main>
  );
}

export function App() {
  const [authentication, setAuthentication] =
    useState<AuthenticationState>("CHECKING");
  const [sessionError, setSessionError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    void fetchSessionStatus()
      .then((session) => {
        if (!active) {
          return;
        }

        setAuthentication(
          session.authenticated ? "AUTHENTICATED" : "UNAUTHENTICATED",
        );
      })
      .catch(() => {
        if (active) {
          setSessionError("Unable to verify an existing telemetry session.");
          setAuthentication("UNAUTHENTICATED");
        }
      });

    return () => {
      active = false;
    };
  }, []);

  function authenticated() {
    setSessionError(null);
    setAuthentication("AUTHENTICATED");
  }

  function logout() {
    setAuthentication("UNAUTHENTICATED");
    setSessionError(null);

    void deleteSession().catch(() => {
      setSessionError(
        "Telemetry was closed locally, but server logout could not be confirmed.",
      );
    });
  }

  if (authentication === "CHECKING") {
    return <SessionCheckingScreen />;
  }

  if (authentication === "UNAUTHENTICATED") {
    return (
      <AccessScreen
        sessionError={sessionError}
        onAuthenticated={authenticated}
      />
    );
  }

  return <TelemetrySurface onLogout={logout} />;
}
