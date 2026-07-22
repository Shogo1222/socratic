import os
import subprocess
import sys
from dataclasses import dataclass


PACKAGE = "demo.refactor_guard"
PROBE_CLASS = f"{PACKAGE}.probes.RenewalBehaviorProbes"
IMPLEMENTATIONS = {"base": f"{PACKAGE}.base", "head": f"{PACKAGE}.head"}


@dataclass(frozen=True)
class Probe:
    method: str
    label: str
    expected: tuple[bool, bool]
    classification: str


PROBES = (
    Probe(
        "test_renews_well_before_the_end_date",
        "renews well before the end date",
        (True, True),
        "preserved",
    ),
    Probe(
        "test_rejects_well_after_the_end_date",
        "rejects well after the end date",
        (True, True),
        "preserved",
    ),
    Probe(
        "test_renews_on_the_exact_end_date",
        "renews on the exact end date",
        (True, False),
        "BEHAVIOR DIFF: changed or removed",
    ),
)


def run(method: str, implementation: str) -> bool:
    environment = os.environ.copy()
    environment["DEMO_IMPL"] = implementation
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "-q", f"{PROBE_CLASS}.{method}"],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=10,
    )
    return completed.returncode == 0


def main() -> int:
    print("Refactor Guard demo: the same behavior probes run on Base and Head")
    print(f"{'Probe':<36} {'Base':<6} {'Head':<6} Classification")
    print("-" * 88)

    unexpected = []
    diffs = []
    for probe in PROBES:
        observed = (run(probe.method, IMPLEMENTATIONS["base"]), run(probe.method, IMPLEMENTATIONS["head"]))
        base_text = "pass" if observed[0] else "FAIL"
        head_text = "pass" if observed[1] else "FAIL"
        print(f"{probe.label:<36} {base_text:<6} {head_text:<6} {probe.classification}")
        if observed != probe.expected:
            unexpected.append(probe.label)
        if observed == (True, False):
            diffs.append(probe)

    if unexpected:
        print(f"\nUnexpected demo result for: {', '.join(unexpected)}")
        return 1

    print("\n1 behavior diff found on a change presented as a pure refactoring:")
    print("  Before: renewal succeeded on the exact end date")
    print("  After:  ExpiredSubscriptionError")
    print("\nThe base is an observed fact, not the specification.")
    print("Required decision: is this change intended?")
    print("  intended   -> false positive; record the new expectation")
    print("  unintended -> strong catch; the refactoring introduced a regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
