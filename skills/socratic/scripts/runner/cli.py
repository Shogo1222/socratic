"""Guided argument parsing and command dispatch for the pinned entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from runner.constants import ARTIFACT_FILES, RunGateError, SCRIPTS_ROOT
from runner.hostapi import ClaudeSocketHostAdapter
from runner.lifecycle import (
    _ready_manifest,
    blocked_preflight,
    cleanup,
    preflight_with_host,
)
from runner.inspection import _resolve_inspect_kind, inspect_review
from runner.scaffolds import (
    SCAFFOLD_EDITABLE_FIELDS,
    SCAFFOLD_FIELD_GUIDES,
    _next_step,
    _probe_next,
    _scaffold_write_protocol,
    runbook,
    scaffold_analysis,
    scaffold_contract,
    scaffold_plan,
    stage_artifact,
)
from runner.execution import (
    challenge_batch,
    doctor,
    execute,
    mutate,
    probe_command,
    register_prebuilt,
)
from runner.reporting import complete, finish

# The entrypoint module owns the user-facing docstring; keep the parser
# description identical to it so guided usage output does not change.
_DESCRIPTION = (
    "Host-gated fail-closed entrypoint for Socratic Review-only mutation runs."
)


def assess_experiment(source_root: Path, plan: Path, evidence: Path) -> dict[str, Any]:
    """Delegate the untrusted prototype path to the typed local-copy Runner."""
    script_root = str(SCRIPTS_ROOT)
    if script_root not in sys.path:
        sys.path.insert(0, script_root)
    try:
        from run_experiment import assess

        return assess(source_root, plan, evidence)
    except (OSError, ValueError, RuntimeError) as error:
        raise RunGateError(str(error)) from error


class _GuidedParser(argparse.ArgumentParser):
    """Raise instead of exiting so argument mistakes return guided JSON."""

    def error(self, message):  # noqa: A003 - argparse API
        raise RunGateError(
            f"invalid-command: {message}; the usage is: {self.format_usage().strip()}; "
            "follow next.argv from the previous Runner result, or run runbook for the pipeline"
        )


def main() -> int:
    parser = _GuidedParser(description=_DESCRIPTION)
    commands = parser.add_subparsers(
        dest="command", required=True, parser_class=_GuidedParser
    )
    runbook_parser = commands.add_parser("runbook")
    runbook_parser.add_argument("--manifest", required=True, type=Path)
    doctor_parser = commands.add_parser("doctor")
    doctor_parser.add_argument("--manifest", required=True, type=Path)
    pre = commands.add_parser("preflight")
    pre.add_argument("--primary", required=True, type=Path)
    pre.add_argument("--host-socket", type=Path)
    pre.add_argument("--host-token")
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("--manifest", required=True, type=Path)
    inspect_parser.add_argument(
        "--kind", choices=("diff", "file", "search", "tests")
    )
    inspect_parser.add_argument(
        "kind_positional", nargs="?", choices=("diff", "file", "search", "tests"),
        metavar="kind",
        help="inspect kind; `inspect diff` and `inspect --kind diff` are equivalent",
    )
    inspect_parser.add_argument("--relative-path")
    inspect_parser.add_argument("--query")
    inspect_parser.add_argument("--start-line", type=int, default=1)
    inspect_parser.add_argument("--end-line", type=int, default=200)
    mutate_parser = commands.add_parser("mutate")
    mutate_parser.add_argument("--manifest", required=True, type=Path)
    mutate_parser.add_argument("--mutation-id", required=True)
    mutate_parser.add_argument("--contract-id", action="append", required=True)
    mutate_parser.add_argument("--relative-path", required=True)
    mutate_parser.add_argument("--content-file", required=True, type=Path)
    register_parser = commands.add_parser("register-prebuilt")
    register_parser.add_argument("--manifest", required=True, type=Path)
    register_parser.add_argument("--mutation-id", required=True)
    register_parser.add_argument("--contract-id", action="append", required=True)
    register_parser.add_argument("--relative-path", required=True)
    execute_parser = commands.add_parser("execute")
    execute_parser.add_argument("--manifest", required=True, type=Path)
    execute_parser.add_argument(
        "--phase", required=True, choices=("prepare", "baseline", "mutation")
    )
    execute_parser.add_argument("--mutation-id")
    execute_parser.add_argument("--timeout", type=int, default=120)
    execute_parser.add_argument(
        "--cwd", default=None,
        help="sandbox-relative working directory, e.g. the focused package",
    )
    execute_parser.add_argument("argv", nargs=argparse.REMAINDER)
    probe_parser = commands.add_parser("probe-command")
    probe_parser.add_argument("--manifest", required=True, type=Path)
    probe_parser.add_argument("--command-id", required=True)
    probe_parser.add_argument("--timeout", type=int, default=120)
    probe_parser.add_argument(
        "--cwd", default=None,
        help="sandbox-relative working directory, e.g. the focused package",
    )
    probe_parser.add_argument("argv", nargs=argparse.REMAINDER)
    batch_parser = commands.add_parser("challenge-batch")
    batch_parser.add_argument("--manifest", required=True, type=Path)
    batch_parser.add_argument("--schema-root", type=Path)
    scaffold_contract_parser = commands.add_parser("scaffold-contract")
    scaffold_contract_parser.add_argument("--manifest", required=True, type=Path)
    scaffold_contract_parser.add_argument("--schema-root", type=Path)
    scaffold_plan_parser = commands.add_parser("scaffold-plan")
    scaffold_plan_parser.add_argument("--manifest", required=True, type=Path)
    scaffold_plan_parser.add_argument("--schema-root", type=Path)
    scaffold_parser = commands.add_parser("scaffold-analysis")
    scaffold_parser.add_argument("--manifest", required=True, type=Path)
    scaffold_parser.add_argument(
        "--mode", required=True, choices=("assessment", "harden", "catch")
    )
    scaffold_parser.add_argument("--schema-root", type=Path)
    stage_parser = commands.add_parser("stage-artifact")
    stage_parser.add_argument("--manifest", required=True, type=Path)
    stage_parser.add_argument(
        "--kind", required=True, choices=tuple(ARTIFACT_FILES)
    )
    stage_parser.add_argument("--schema-root", type=Path)
    finish_parser = commands.add_parser("finish")
    finish_parser.add_argument("--manifest", required=True, type=Path)
    finish_parser.add_argument("--schema-root", type=Path)
    cleanup_parser = commands.add_parser("cleanup")
    cleanup_parser.add_argument("--manifest", required=True, type=Path)
    complete_parser = commands.add_parser("complete")
    complete_parser.add_argument("--manifest", required=True, type=Path)
    complete_parser.add_argument(
        "--retention", choices=("discard", "keep"), default="discard"
    )
    complete_parser.add_argument("--schema-root", type=Path)
    assess_parser = commands.add_parser(
        "assess", help="run the unsigned v0.4 local-copy prototype"
    )
    assess_parser.add_argument("--source-root", required=True, type=Path)
    assess_parser.add_argument("--plan", required=True, type=Path)
    assess_parser.add_argument("--evidence", required=True, type=Path)
    try:
        args = parser.parse_args()
    except RunGateError as error:
        print(json.dumps(
            {"status": "invalid-command", "error": str(error)}, sort_keys=True
        ))
        return 2
    if args.command == "preflight":
        try:
            adapter = (
                ClaudeSocketHostAdapter(args.host_socket, args.host_token)
                if args.host_socket is not None and args.host_token is not None
                else ClaudeSocketHostAdapter.from_environment()
            )
            manifest, manifest_path = preflight_with_host(
                args.primary, adapter
            )
        except (OSError, RunGateError) as error:
            try:
                blocked = blocked_preflight(args.primary)
            except (OSError, RunGateError):
                blocked = {
                    "status": "blocked",
                    "terminal": True,
                    "next_action": "stop",
                    "primary_root": str(args.primary),
                    "blocked_reason": str(error),
                    "missing_host_capability": "trusted HostAdapter capability",
                }
            print(json.dumps(blocked, sort_keys=True))
            return 2
        print(json.dumps({
            "status": "ready", "run_id": manifest["run_id"],
            "manifest_path": str(manifest_path),
            "sandbox_root": manifest["sandbox_root"],
            "prepared_root": manifest["prepared_root"],
            "dependency_root": manifest["dependency_root"],
            "artifact_root": manifest["artifact_root"],
            "next": _next_step(
                "runbook", "--manifest", str(manifest_path),
                note=(
                    "read the runbook once: it explains the IDs, the gates, the "
                    "fields you may edit, and returns the exact next command. "
                    "Every later Runner result carries next.argv — run it "
                    "verbatim instead of guessing arguments"
                ),
            ),
            "allowed_operations": [
                "runbook", "inspect", "doctor", "execute", "probe-command",
                "scaffold-contract", "stage-artifact", "scaffold-plan",
                "challenge-batch", "scaffold-analysis", "complete", "cleanup",
            ],
        }, sort_keys=True))
        return 0
    try:
        if args.command == "runbook":
            print(json.dumps(
                runbook(args.manifest), ensure_ascii=False, sort_keys=True
            ))
        elif args.command == "doctor":
            print(json.dumps(
                doctor(args.manifest), ensure_ascii=False, sort_keys=True
            ))
        elif args.command == "inspect":
            print(json.dumps(inspect_review(
                args.manifest,
                _resolve_inspect_kind(args.kind, args.kind_positional),
                relative_path=args.relative_path,
                query=args.query,
                start_line=args.start_line,
                end_line=args.end_line,
            ), ensure_ascii=False, sort_keys=True))
        elif args.command == "mutate":
            mutate(
                args.manifest, args.mutation_id, args.contract_id,
                args.relative_path, args.content_file.read_bytes(),
            )
        elif args.command == "register-prebuilt":
            register_prebuilt(
                args.manifest, args.mutation_id, args.contract_id, args.relative_path
            )
        elif args.command == "execute":
            if not args.argv:
                raise RunGateError("execute requires a command after --")
            argv = args.argv[1:] if args.argv[0] == "--" else args.argv
            returncode = execute(
                args.manifest, args.phase, args.mutation_id, argv, args.timeout,
                cwd_relative=args.cwd,
            )
            if args.phase == "prepare":
                if returncode == 0:
                    print(json.dumps({
                        "phase": "prepare", "returncode": returncode,
                        "next": _probe_next(args.manifest),
                    }, ensure_ascii=False, sort_keys=True))
                else:
                    print(json.dumps({
                        "phase": "prepare", "returncode": returncode,
                        "status": "prepare-failed",
                        "hint": (
                            "read the command output above; if it mentions "
                            "versioningit, setuptools-scm, hatch-vcs, or 'not a "
                            "git repository', the prepared snapshot intentionally "
                            "has no .git — SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 "
                            "is preset, and versioningit projects need "
                            "tool.versioningit.default-version; if it mentions "
                            "Requires-Python, rerun with the project's own "
                            "interpreter by absolute path instead of the plugin "
                            "runtime Python; if the tool itself was not found, "
                            "HOME redirection hides HOME-based shims (uv, nvm, "
                            "pyenv) — invoke it by absolute path"
                        ),
                        "diagnose": _next_step(
                            "doctor", "--manifest", str(args.manifest),
                            note=(
                                "read-only sandbox toolchain and environment "
                                "report; run it before changing tools or arguments"
                            ),
                        ),
                        "next": _next_step(
                            "execute", "--phase", "prepare",
                            "--manifest", str(args.manifest),
                            "--", "<corrected-install-argv>",
                            note="fix the environment cause, then rerun prepare",
                        ),
                    }, ensure_ascii=False, sort_keys=True))
            return returncode
        elif args.command == "probe-command":
            if not args.argv:
                raise RunGateError("probe-command requires a command after --")
            argv = args.argv[1:] if args.argv[0] == "--" else args.argv
            result = probe_command(
                args.manifest, args.command_id, argv, args.timeout,
                cwd_relative=args.cwd
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["status"] == "ready" else 2
        elif args.command == "challenge-batch":
            print(json.dumps(
                challenge_batch(args.manifest, args.schema_root), sort_keys=True
            ))
        elif args.command == "scaffold-contract":
            manifest = _ready_manifest(args.manifest)
            print(json.dumps({
                "artifact": ARTIFACT_FILES["contract"],
                **_scaffold_write_protocol(
                    manifest, ARTIFACT_FILES["contract"]
                ),
                "editable_fields": SCAFFOLD_EDITABLE_FIELDS["contract"],
                "field_guide": SCAFFOLD_FIELD_GUIDES["contract"],
                "document": scaffold_contract(args.manifest, args.schema_root),
                "next": _next_step(
                    "stage-artifact", "--manifest", str(args.manifest),
                    "--kind", "contract",
                    note=(
                        "fill every replace-me value, then Write document once to "
                        "artifact_path; the Runner owns the JSON structure"
                    ),
                ),
            }, ensure_ascii=False, sort_keys=True))
        elif args.command == "scaffold-plan":
            manifest = _ready_manifest(args.manifest)
            print(json.dumps({
                "artifact": "challenge-plan.json",
                **_scaffold_write_protocol(manifest, "challenge-plan.json"),
                "editable_fields": SCAFFOLD_EDITABLE_FIELDS["plan"],
                "field_guide": SCAFFOLD_FIELD_GUIDES["plan"],
                "document": scaffold_plan(args.manifest, args.schema_root),
                "next": _next_step(
                    "challenge-batch", "--manifest", str(args.manifest),
                    note=(
                        "fill the placeholder challenge, then Write document once "
                        "to artifact_path; run synchronously in the foreground"
                    ),
                ),
            }, ensure_ascii=False, sort_keys=True))
        elif args.command == "scaffold-analysis":
            scaffold = scaffold_analysis(args.manifest, args.mode, args.schema_root)
            manifest = _ready_manifest(args.manifest)
            print(json.dumps({
                "artifact": "review-analysis.json",
                **_scaffold_write_protocol(manifest, "review-analysis.json"),
                "editable_fields": SCAFFOLD_EDITABLE_FIELDS["analysis"],
                "field_guide": SCAFFOLD_FIELD_GUIDES["analysis"],
                "document": scaffold["document"],
                "scaffold": scaffold,
                "next": _next_step(
                    "complete", "--manifest", str(args.manifest),
                    "--retention", "discard",
                    note=(
                        "edit only semantic judgments, Write document once to "
                        "artifact_path, then complete renders and cleans up; use "
                        "--retention keep only after an explicit user choice"
                    ),
                ),
            }, ensure_ascii=False, sort_keys=True))
        elif args.command == "stage-artifact":
            staged = stage_artifact(args.manifest, args.kind, args.schema_root)
            if args.kind == "contract":
                staged = dict(staged)
                staged["next"] = _next_step(
                    "execute", "--phase", "prepare",
                    "--manifest", str(args.manifest),
                    "--", "<dependency-install-argv>",
                    note=(
                        "install dependencies once; if the repository needs no "
                        "install, skip straight to probe-command"
                    ),
                )
                staged["skip_if_dependencies_ready"] = _probe_next(args.manifest)
            print(json.dumps(staged, ensure_ascii=False, sort_keys=True))
        elif args.command == "finish":
            sys.stdout.write(finish(args.manifest, args.schema_root))
        elif args.command == "cleanup":
            cleanup(args.manifest)
        elif args.command == "complete":
            sys.stdout.write(complete(
                args.manifest,
                retention=args.retention,
                schema_root=args.schema_root,
            ))
        elif args.command == "assess":
            print(json.dumps(
                assess_experiment(args.source_root, args.plan, args.evidence),
                sort_keys=True,
            ))
        return 0
    except (OSError, RunGateError) as error:
        guided: dict[str, Any] = {
            "status": "error",
            "command": args.command,
            "error": str(error),
        }
        manifest_argument = getattr(args, "manifest", None)
        if manifest_argument is not None:
            guided["next"] = _next_step(
                "runbook", "--manifest", str(manifest_argument),
                note=(
                    "review the runbook gate order, fix the reported cause, then "
                    "rerun the failed command; after a terminal complete failure, "
                    "start a fresh run instead of retrying this manifest"
                ),
            )
        print(json.dumps(guided, ensure_ascii=False, sort_keys=True))
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
