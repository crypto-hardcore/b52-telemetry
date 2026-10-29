# Telemetry transport operations

Perform lifecycle operations with the B-52.io receiver stopped. Never stop or
modify B-52. Replace registry and relay configuration through a same-filesystem
temporary file, file `fsync`, atomic rename, and parent-directory `fsync`. Install
producer credentials from a protected input file; never place a plaintext token
in an environment variable, command argument, registry, or log. Start a service
only after its configured generation and persisted generation agree.

The receiver is `b52-telemetry.service`, running as the dedicated
`b52-telemetry:b52-telemetry` identity. Systemd creates
`/var/lib/b52-telemetry` as `b52-telemetry:b52-telemetry` with mode `0700`.
Install `/etc/b52-telemetry/application.env` through a same-filesystem temporary
file as `root:root` with mode `0600`, file-fsync it, atomically rename it, and
fsync `/etc/b52-telemetry`. Privileged configuration installation runs as root;
receiver-state administration runs as `b52-telemetry` while the receiver is
stopped. The receiver unit reads the root-owned environment file through
systemd; the service identity does not require direct access to that file.

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

1. Run `sudo systemctl stop b52-telemetry.service` on the receiver VPS and leave
   `b52-telemetry-relay@B52-001.service` stopped on the engine VPS.
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
5. Run `sudo -u b52-telemetry
   /opt/b52-telemetry/venv/bin/b52-telemetry-admin receiver-baseline --instance
   B52-001 --generation 1 --snapshot
   /var/lib/b52-telemetry/B52-001/telemetry.latest.json` on the receiver VPS.
6. Run `sudo -u b52 /opt/b52-telemetry/venv/bin/b52-telemetry-admin
   relay-initialize --instance B52-001 --generation 1 --state
   /var/lib/b52-relay/B52-001/state.json` on the engine VPS. This binds the
   persisted relay state to the same identity and generation.
7. Atomically enable the registry entry without changing its digest or
   generation. Verify the registry generation and receiver control xattr are 1,
   and the relay environment and persisted state generation are 1.
8. Run `sudo systemctl enable --now b52-telemetry.service` and validate the
   receiver. Only then start the confined relay with `sudo systemctl start
   b52-telemetry-relay@B52-001.service` on the engine VPS.

## Planned credential rotation

Provision a new independent 256-bit token through the approved secret-delivery
channel before beginning. Ordinary rotation changes authorization generation but
preserves both the receiver HWM and the relay's last assigned sequence.

1. Run `sudo systemctl stop b52-telemetry-relay@B52-001.service` on the engine
   VPS, then `sudo systemctl stop b52-telemetry.service` on the receiver VPS. No
   request authenticated by the old credential can commit after the receiver
   has stopped.
2. Atomically install the registry entry disabled with generation N+1 and only
   the new token's SHA-256 digest.
3. Run `sudo -u b52-telemetry
   /opt/b52-telemetry/venv/bin/b52-telemetry-admin receiver-generation
   --instance B52-001 --previous-generation N --generation N+1 --snapshot
   /var/lib/b52-telemetry/B52-001/telemetry.latest.json`. This preserves the
   accepted snapshot and HWM.
4. Run `sudo -u b52 /opt/b52-telemetry/venv/bin/b52-telemetry-admin
   relay-rotate --instance B52-001 --previous-generation N --generation N+1 --state
   /var/lib/b52-relay/B52-001/state.json` on the engine VPS. This preserves the
   last assigned sequence.
5. Atomically replace `/etc/b52-relay/B52-001/producer.token` with the new
   protected input file, owned by `root:root` with mode `0600`.
6. Atomically update `/etc/b52-relay/B52-001/relay.env` so
   `B52_RELAY_AUTHORIZATION_GENERATION=N+1`.
7. Verify the registry and receiver control xattr generations are N+1, and the
   relay environment and persisted state generations are N+1. Atomically enable
   the registry entry without changing its new digest or generation.
8. Run `sudo systemctl start b52-telemetry.service` and validate the receiver,
   then run `sudo systemctl start b52-telemetry-relay@B52-001.service` on the
   engine VPS. Requests carrying the old credential or generation cannot commit
   in the new receiver process.

If interrupted, keep both services stopped and resume the same N to N+1
operation. A generation mismatch fails closed; do not increment again merely to
recover from an interrupted rotation.

## Credential revocation

1. Run `sudo systemctl stop b52-telemetry-relay@B52-001.service` on the engine
   VPS, then `sudo systemctl stop b52-telemetry.service` on the receiver VPS.
   Completion of receiver stop is the revocation boundary: no old in-flight
   request can commit afterward.
2. Atomically set that existing registry entry to `enabled=false`. Do not alter
   its generation, accepted snapshot, HWM, receiver control xattr, or relay state.
3. Run `sudo systemctl start b52-telemetry.service` and validate it with the
   entry disabled. Leave the relay stopped. The producer endpoint rejects that
   credential while browser access remains governed independently.

Re-enablement with a new credential is a planned credential rotation from the
preserved generation and HWM; do not bootstrap or reset ordering.

## Explicit ordering reset

1. Run `sudo systemctl stop b52-telemetry-relay@B52-001.service` on the engine
   VPS, then `sudo systemctl stop b52-telemetry.service` on the receiver VPS.
2. Atomically install generation N+1 disabled with a new credential digest in
   `/etc/b52-telemetry/application.env` as root.
3. Run `sudo -u b52-telemetry
   /opt/b52-telemetry/venv/bin/b52-telemetry-admin receiver-reset --instance
   B52-001 --previous-generation N --generation N+1 --snapshot
   /var/lib/b52-telemetry/B52-001/telemetry.latest.json` on the receiver VPS.
4. Run `sudo -u b52 /opt/b52-telemetry/venv/bin/b52-telemetry-admin relay-reset
   --instance B52-001 --previous-generation N --generation N+1 --state
   /var/lib/b52-relay/B52-001/state.json` on the engine VPS.
5. Atomically install the new relay credential and generation configuration,
   verify both sides agree, and atomically enable the receiver registry entry.
6. Run `sudo systemctl start b52-telemetry.service` and validate it, then run
   `sudo systemctl start b52-telemetry-relay@B52-001.service` on the engine VPS.
   No timestamp, surviving payload, or receiver response reconstructs ordering.

An interrupted operation leaves a disabled entry or generation/metadata mismatch
that fails closed. Resume the same generation change; do not increment again unless
deliberately beginning another authorized reset.
