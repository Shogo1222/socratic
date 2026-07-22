import os
import subprocess
import sys
from dataclasses import dataclass


PACKAGE = "demo.test_assessment"
COHORTS = {
    "existing": f"{PACKAGE}.tests_existing",
    "changed": f"{PACKAGE}.tests_changed",
}
ORIGINAL = f"{PACKAGE}.pricing"


@dataclass(frozen=True)
class Mutant:
    identifier: str
    implementation: str
    incident: str
    expected: tuple[bool, bool]
    classification: str


# expected = (existing cohort passes, changed cohort passes); a pass means SURVIVED.
MUTANTS = (
    Mutant(
        "MUT-001",
        f"{PACKAGE}.mutants.volume_boundary",
        "discount starts one item too late",
        (False, True),
        "protection-regression",
    ),
    Mutant(
        "MUT-002",
        f"{PACKAGE}.mutants.missing_volume_discount",
        "volume discount omitted",
        (False, False),
        "existing-protection",
    ),
    Mutant(
        "MUT-003",
        f"{PACKAGE}.mutants.missing_validation",
        "negative quantity accepted",
        (True, True),
        "unprotected",
    ),
    Mutant(
        "MUT-004",
        f"{PACKAGE}.mutants.missing_bulk_tier",
        "bulk tier falls back to 10%",
        (True, False),
        "incremental-protection",
    ),
)


def run(tests: str, implementation: str) -> bool:
    environment = os.environ.copy()
    environment["DEMO_IMPL"] = implementation
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "-q", tests],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=10,
    )
    return completed.returncode == 0


def outcome(passed: bool) -> str:
    return "survived" if passed else "killed"


def main() -> int:
    print("Test Assessment demo: the same mutants run on both test cohorts")

    for cohort, tests in COHORTS.items():
        if not run(tests, ORIGINAL):
            print(f"Unexpected demo result: {cohort} cohort baseline is red")
            return 1
    print("Baselines: both cohorts pass on the original code\n")

    print(f"{'Mutant':<9} {'Incident':<34} {'Existing':<10} {'Changed':<10} Classification")
    print("-" * 92)

    unexpected = []
    for mutant in MUTANTS:
        observed = (
            run(COHORTS["existing"], mutant.implementation),
            run(COHORTS["changed"], mutant.implementation),
        )
        print(
            f"{mutant.identifier:<9} {mutant.incident:<34} "
            f"{outcome(observed[0]):<10} {outcome(observed[1]):<10} {mutant.classification}"
        )
        if observed != mutant.expected:
            unexpected.append(mutant.identifier)

    if unexpected:
        print(f"\nUnexpected demo result for: {', '.join(unexpected)}")
        return 1

    print("\nWhat the AI's test edit actually did:")
    print("  + incremental-protection: the new bulk-tier test catches a bug nothing caught before")
    print("  - protection-regression:  weakening the boundary assertion un-catches MUT-001")
    print("  = existing-protection:    the volume-discount omission was already covered")
    print("  ! unprotected:            negative quantities were never protected by either suite")
    print("\nGreen tests are not the question; detection is.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
