import os
import subprocess
import sys
from dataclasses import dataclass


PACKAGE = "demo.subscription_renewal"


@dataclass(frozen=True)
class Scenario:
    label: str
    implementation: str
    tests: str
    expected_pass: bool
    interpretation: str


SCENARIOS = (
    Scenario("Original / weak", f"{PACKAGE}.subscription", f"{PACKAGE}.test_weak", True, "baseline passes"),
    Scenario("MUT-001 / weak", f"{PACKAGE}.mutants.boundary", f"{PACKAGE}.test_weak", True, "SURVIVED"),
    Scenario("MUT-002 / weak", f"{PACKAGE}.mutants.missing_charge", f"{PACKAGE}.test_weak", True, "SURVIVED"),
    Scenario("MUT-003 / weak", f"{PACKAGE}.mutants.non_idempotent", f"{PACKAGE}.test_weak", True, "SURVIVED"),
    Scenario("Original / hardened", f"{PACKAGE}.subscription", f"{PACKAGE}.test_hardened", True, "baseline passes"),
    Scenario("MUT-001 / hardened", f"{PACKAGE}.mutants.boundary", f"{PACKAGE}.test_hardened", False, "KILLED"),
    Scenario("MUT-002 / hardened", f"{PACKAGE}.mutants.missing_charge", f"{PACKAGE}.test_hardened", False, "KILLED"),
    Scenario("MUT-003 / hardened", f"{PACKAGE}.mutants.non_idempotent", f"{PACKAGE}.test_hardened", False, "KILLED"),
)


def run(scenario: Scenario) -> tuple[bool, str]:
    environment = os.environ.copy()
    environment["DEMO_IMPL"] = scenario.implementation
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "-q", scenario.tests],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=10,
    )
    return completed.returncode == 0, completed.stdout + completed.stderr


def main() -> int:
    unexpected: list[tuple[Scenario, str]] = []
    print(f"{'Scenario':<24} {'Tests':<6} Interpretation")
    print("-" * 55)

    for scenario in SCENARIOS:
        passed, output = run(scenario)
        observed = "PASS" if passed else "FAIL"
        print(f"{scenario.label:<24} {observed:<6} {scenario.interpretation}")
        if passed != scenario.expected_pass:
            unexpected.append((scenario, output))

    if unexpected:
        print("\nUnexpected demo result:")
        for scenario, output in unexpected:
            print(f"\n[{scenario.label}]\n{output.strip()}")
        return 1

    print("\nDemo succeeded: weak tests miss all three risks; hardened tests detect them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
