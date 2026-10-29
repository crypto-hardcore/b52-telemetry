# Telemetry transport operations

Perform lifecycle operations with the B-52.io receiver stopped. Never stop or
modify B-52. Replace registry and relay configuration through a same-filesystem
temporary file, file `fsync`, atomic rename, and parent-directory `fsync`. Install
producer credentials from a protected input file; never place a plaintext token
in an environment variable, command argument, registry, or log. Start a service
only after its configured generation and persisted generation agree.

## Initial engine bootstrap

For each engine, provision one independently generated 256-bit producer token
through the approved secret-delivery channel. The protected input file used
below contains only that token and ends with an optional newline.

Derive the receiver digest from the same normalized bytes that the relay uses,
without placing the token in an argument or environment variable:

```sh
python3 -c 'from hashlib import sha256; from pathlib import Path; import sys; token = Path(sys.argv[1]).read_text(encoding="utf-8").strip(); print(sha256(token.encode()).hexdigest())' /protected/path/producer.token
```

The printed digest is not the relay credential. Store only that digest in
`B52_TELEMETRY_SOURCES`. To install the plaintext credential, create a mode
`0600`, `root:root` temporary file in `/etc/b52-relay/B52-001`, file-fsync it,
rename it to `producer.token`, and fsync that directory. Remove the protected
input according to the approved secret-delivery procedure.

1. Stop the receiver and leave the new relay stopped.
2. Compute the token's SHA-256 digest without copying the plaintext token into
   shell history. Add the engine to `B52_TELEMETRY_SOURCES` disabled, with
   generation 1, its canonical accepted path, and only that digest. Atomically
   install the receiver configuration.
3. On the engine VPS, atomically install the protected input file as
   `/etc/b52-relay/B52-001/producer.token`, owned by `root:root` with mode `0600`.
   This is the source for the unit's existing
   `LoadCredential=producer.token:...` directive.
4. Atomically install `/etc/b52-relay/B52-001/relay.env` with
   `B52_RELAY_AUTHORIZATION_GENERATION=1` and the remaining values shown in
   `relay.env.example`. The environment file contains no credential.
5. Run `b52-telemetry-admin receiver-baseline --instance B52-001 --generation 1
   --snapshot /var/lib/b52-telemetry/B52-001/telemetry.latest.json` on the
   receiver VPS.
6. Run `b52-telemetry-admin relay-initialize --instance B52-001 --generation 1
   --state /var/lib/b52-relay/B52-001/state.json` on the engine VPS. This binds
   the persisted relay state to the same identity and generation.
7. Atomically enable the registry entry without changing its digest or
   generation. Verify the registry generation and receiver control xattr are 1,
   and the relay environment and persisted state generation are 1.
8. Start and validate the receiver, then start the confined relay.

## Planned credential rotation

Provision a new independent 256-bit token through the approved secret-delivery
channel before beginning. Ordinary rotation changes authorization generation but
preserves both the receiver HWM and the relay's last assigned sequence.

1. Stop the affected relay, then stop the receiver. No request authenticated by
   the old credential can commit after the receiver has stopped.
2. Atomically install the registry entry disabled with generation N+1 and only
   the new token's SHA-256 digest.
3. Run `b52-telemetry-admin receiver-generation --instance B52-001
   --previous-generation N --generation N+1 --snapshot
   /var/lib/b52-telemetry/B52-001/telemetry.latest.json`. This preserves the
   accepted snapshot and HWM.
4. Run `b52-telemetry-admin relay-rotate --instance B52-001
   --previous-generation N --generation N+1 --state
   /var/lib/b52-relay/B52-001/state.json` on the engine VPS. This preserves the
   last assigned sequence.
5. Atomically replace `/etc/b52-relay/B52-001/producer.token` with the new
   protected input file, owned by `root:root` with mode `0600`.
6. Atomically update `/etc/b52-relay/B52-001/relay.env` so
   `B52_RELAY_AUTHORIZATION_GENERATION=N+1`.
7. Verify the registry and receiver control xattr generations are N+1, and the
   relay environment and persisted state generations are N+1. Atomically enable
   the registry entry without changing its new digest or generation.
8. Start and validate the receiver, then start the relay. Requests carrying the
   old credential or generation cannot commit in the new receiver process.

If interrupted, keep both services stopped and resume the same N to N+1
operation. A generation mismatch fails closed; do not increment again merely to
recover from an interrupted rotation.

## Credential revocation

1. Stop the affected relay, then stop the receiver. Completion of receiver stop
   is the revocation boundary: no old in-flight request can commit afterward.
2. Atomically set that existing registry entry to `enabled=false`. Do not alter
   its generation, accepted snapshot, HWM, receiver control xattr, or relay state.
3. Restart and validate the receiver with the entry disabled. Leave the relay
   stopped. The producer endpoint rejects that credential while browser access
   remains governed independently.

Re-enablement with a new credential is a planned credential rotation from the
preserved generation and HWM; do not bootstrap or reset ordering.

## Explicit ordering reset

Stop the receiver and affected relay. Install generation N+1 disabled with a new
credential digest. Run `receiver-reset` and `relay-reset` with N and N+1. Enable
the entry, start and validate the receiver, then start the relay. No timestamp,
surviving payload, or receiver response reconstructs ordering.

An interrupted operation leaves a disabled entry or generation/metadata mismatch
that fails closed. Resume the same generation change; do not increment again unless
deliberately beginning another authorized reset.
