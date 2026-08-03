"""Hash-linked, tamper-evident audit event log.

`types.py` centralizes `AuditEventType`/`ActorType`. `canonical.py` provides
deterministic canonical JSON serialization for hashing. `hashing.py` builds
the documented hash envelope and computes SHA-256 event hashes, chained via
`previous_hash`/`event_hash` from a genesis hash of 64 zero characters.
`service.py` implements the only way an event is ever created
(`append_event`) plus `list_events`. `verification.py` implements
`verify_chain` (sequence continuity and hash-chain integrity) and
`build_provenance` (an ordered, chain-validity-annotated trace).

Tamper-evident, not tamper-proof: this is plain hash chaining with the
standard-library `hashlib.sha256`, not a digital signature or external
notarization. `cryptography` is intentionally not used — verifying internal
consistency of a local SQLite audit log doesn't need asymmetric signing.
"""
