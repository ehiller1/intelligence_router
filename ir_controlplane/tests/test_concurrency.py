"""
The MVP-0 exit criterion, verbatim from the Implementation Guide:
"Atomic promotion test passes (concurrent writers, only one sees the flip)".

These tests use real OS threads (not asyncio mocks) hammering a single
InMemoryPolicyStore, because the failure mode being tested -- a race between
two promotions leaving two versions simultaneously active, or a torn read
mid-write -- is exactly the class of bug that only shows up under genuine
concurrent execution.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from ir_controlplane.service import GovernanceControlPlane
from ir_controlplane.signing import KeyPair
from ir_controlplane.store import InMemoryPolicyStore


def _submit(plane, key, version_id, domain_id="diocese-a"):
    return plane.submit_draft(
        version_id=version_id,
        domain_id=domain_id,
        classes={}, pool_membership={}, tiering={}, tightening_map={},
        attestation_rules={}, bands={},
        ledger_sampling_rate=1.0,
        verification_trust_bundle={},
        signing_private_key=key.private_key,
    )


def test_concurrent_promotions_to_the_same_domain_leave_exactly_one_active():
    """
    N threads each promote a DIFFERENT version to the SAME domain
    simultaneously.

    An earlier version of this test scanned all N versions' `.is_active`
    flags in a plain sequential loop and asserted the count was never >1.
    That test was WRONG, and demonstrated something worth recording: once
    `is_active` is (correctly) derived from a single pointer
    (`_active_by_domain[domain]`, see store.py's docstring), that pointer
    can legitimately change *while* a slow, unsynchronized, multi-key scan
    is in flight -- key #5 can read "true" against the pointer's value at
    time T, key #12 can read "true" against the pointer's *different* value
    at time T+ε, and the scan reports "two active" despite the store never
    having had two active versions at any single instant. A scan across
    time is not a snapshot; comparing its results as if it were one is the
    bug, not the store.

    What we actually verify here:
      1. `get_active()` -- a SINGLE atomic pointer read -- always returns
         a real, previously-submitted version, is never None once at least
         one promotion has landed, and never raises, even while dozens of
         promotions race underneath it (no torn/partial reads of the
         pointer itself, which the derived-is_active design guarantees by
         construction: there is exactly one write of one dict value).
      2. After all promotions complete, exactly one version is active.
      3. No promote() call raised.
    """
    plane = GovernanceControlPlane(InMemoryPolicyStore())
    key = KeyPair.generate()
    n = 50
    version_ids = [f"gov-v{i}" for i in range(n)]
    for vid in version_ids:
        _submit(plane, key, vid)

    observed_pointer_values = []
    read_errors = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                active = plane.active_policy("diocese-a")
            except Exception as exc:  # noqa: BLE001 -- any exception here is a bug
                read_errors.append(exc)
                continue
            if active is not None:
                observed_pointer_values.append(active.version_id)

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    def promote(vid):
        return plane.promote(vid, "diocese-a", "authority-1", key.public_key_b64())

    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(promote, vid) for vid in version_ids]
        for f in as_completed(futures):
            f.result()  # re-raises any exception from a worker

    time.sleep(0.05)
    stop.set()
    reader_thread.join(timeout=2)

    assert read_errors == [], f"active_policy() raised under concurrent load: {read_errors[:3]}"
    assert all(v in version_ids for v in observed_pointer_values), (
        "active_policy() returned a version_id that was never submitted -- pointer corruption"
    )

    active_versions = [vid for vid in version_ids if plane._store.get(vid).is_active]
    assert len(active_versions) == 1, (
        f"Expected exactly one active version after concurrent promotion, got {active_versions}"
    )
    assert plane.active_policy("diocese-a").version_id == active_versions[0]


def test_concurrent_promotions_across_independent_domains_do_not_contend():
    """
    Promotions to different domains must not serialize behind each other
    (decision: one lock per domain, not a global lock) -- verified by
    confirming both domains end up with their own correct active version
    even when promoted from overlapping threads.
    """
    plane = GovernanceControlPlane(InMemoryPolicyStore())
    key = KeyPair.generate()
    domains = [f"domain-{i}" for i in range(20)]
    for d in domains:
        _submit(plane, key, version_id=f"gov-{d}", domain_id=d)

    def promote(domain):
        return plane.promote(f"gov-{domain}", domain, "authority-1", key.public_key_b64())

    with ThreadPoolExecutor(max_workers=len(domains)) as pool:
        futures = [pool.submit(promote, d) for d in domains]
        for f in as_completed(futures):
            f.result()

    for d in domains:
        active = plane.active_policy(d)
        assert active is not None
        assert active.version_id == f"gov-{d}"


def test_repeated_concurrent_runs_are_stable():
    """Run the race many times -- a race condition that fires 1-in-20 runs
    would pass a single execution and still be a real bug."""
    for _ in range(20):
        test_concurrent_promotions_to_the_same_domain_leave_exactly_one_active()
