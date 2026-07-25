#!/usr/bin/env python3
"""Tests for the intent-question eval: fixtures, question detection, scoring, matrix.

Every test here is offline: no `claude`, no network, and nothing written outside
a temporary directory.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import ROOT, load_module

MODULE = ROOT / "tools/devloop/intent_eval.py"


def _tool_use(name: str, payload: dict) -> str:
    return json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": name, "input": payload}]},
    })


def _text(text: str, event_type: str = "assistant") -> str:
    return json.dumps({"type": event_type, "message": {"content": [{"type": "text", "text": text}]}})


def _contract(**overrides) -> dict:
    document = {
        "version": 1,
        "status": "provisional",
        "decisions": [
            {
                "id": "DEC-001",
                "question": "Is a renewal on the end date rejected?",
                "expected": "Yes; equality is expired",
                "provenance": "user-confirmed",
            }
        ],
        "unresolved": [],
    }
    document.update(overrides)
    return document


def _established(citations) -> dict:
    decision = {
        "id": "DEC-001",
        "question": "Is a renewal on the end date rejected?",
        "expected": "Yes; equality is expired",
        "provenance": "repository-established",
    }
    if citations is not None:
        decision["citations"] = citations
    return _contract(decisions=[decision])


class IntentEvalScoringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.eval = load_module("devloop_intent_eval", MODULE)

    # -- asked_human ------------------------------------------------------

    def test_asked_human_detects_the_host_question_tool_call(self) -> None:
        lines = [
            _text("Reading the diff"),
            _tool_use("AskUserQuestion", {"questions": [{"question": "Which boundary?"}]}),
        ]
        self.assertTrue(self.eval.asked_human(lines))
        self.assertEqual(self.eval.question_tool_calls(lines), ["AskUserQuestion"])

    def test_asked_human_accepts_decoded_events_and_namespaced_tools(self) -> None:
        events = [json.loads(_tool_use("mcp__codex__request_user_input", {"prompt": "?"}))]
        self.assertTrue(self.eval.asked_human(events))

    def test_asked_human_is_false_without_a_question_tool_call(self) -> None:
        lines = [
            _text("The repository already settles the boundary, so I will not ask."),
            _tool_use("Read", {"file_path": "docs/renewal.md"}),
            "not json at all",
        ]
        self.assertFalse(self.eval.asked_human(lines))
        self.assertEqual(self.eval.question_tool_calls(lines), [])

    def test_markdown_fallback_is_advisory_and_never_confused_with_the_tool(self) -> None:
        rendered = _text(
            "Should renewal succeed on the exact end date?\n\n"
            "A. allow\n   The end date is inside the valid period.\n"
            "B. reject\n   The account is expired starting on the end date.\n"
        )
        self.assertTrue(self.eval.markdown_question_seen([rendered]))
        self.assertFalse(self.eval.asked_human([rendered]))
        self.assertFalse(self.eval.markdown_question_seen([_text("No question here.")]))

    # -- contract_verdict -------------------------------------------------

    def test_contract_verdict_reports_provenance_unresolved_and_citations(self) -> None:
        verdict = self.eval.contract_verdict(_established(
            [{"path": "docs/renewal.md", "quote": self.eval.DECIDING_SENTENCE}]
        ))
        self.assertTrue(verdict["contract_found"])
        self.assertTrue(verdict["decisions_readable"])
        self.assertEqual(verdict["status"], "provisional")
        self.assertEqual(verdict["provenances"], ["repository-established"])
        self.assertEqual(verdict["repository_established"], 1)
        self.assertEqual(verdict["citations"], 1)
        self.assertEqual(verdict["unresolved"], 0)
        self.assertTrue(verdict["citations_verified"])
        self.assertEqual(verdict["problems"], [])

    def test_contract_verdict_flags_a_repository_claim_without_citations(self) -> None:
        for citations in (None, [], [{"path": "docs/renewal.md"}], [{"quote": " "}], ["nope"]):
            verdict = self.eval.contract_verdict(_established(citations))
            self.assertFalse(verdict["citations_verified"], citations)
            self.assertIn("DEC-001", verdict["problems"][0])

    def test_contract_verdict_counts_unresolved_items(self) -> None:
        verdict = self.eval.contract_verdict(_contract(
            status="needs-decision",
            unresolved=[{"id": "UNR-001", "statement": "which boundary", "test_impact": "oracle"}],
        ))
        self.assertEqual(verdict["unresolved"], 1)
        self.assertTrue(self.eval.requested_human(False, verdict))

    def test_contract_verdict_survives_untrusted_shapes(self) -> None:
        for document in (None, "a string", [], {"decisions": "not a list"}):
            verdict = self.eval.contract_verdict(document)
            self.assertFalse(verdict["decisions_readable"], document)
            self.assertTrue(verdict["problems"], document)
        partial = self.eval.contract_verdict({"decisions": ["not an object"], "unresolved": {}})
        self.assertTrue(partial["decisions_readable"])
        self.assertEqual(partial["unresolved"], 0)
        self.assertEqual(partial["repository_established"], 0)

    # -- score ------------------------------------------------------------

    def _score(self, case: str, asked: bool, document) -> str:
        return self.eval.score(case, asked, self.eval.contract_verdict(document))

    def test_score_labels_every_cell(self) -> None:
        cited = _established([{"path": "docs/renewal.md", "quote": "rejected"}])
        needs_decision = _contract(
            status="needs-decision",
            unresolved=[{"id": "UNR-001", "statement": "which boundary", "test_impact": "oracle"}],
        )
        self.assertEqual(self._score("settled", False, cited), "correct-silent")
        self.assertEqual(self._score("settled", True, cited), "spurious-question")
        self.assertEqual(self._score("settled", False, needs_decision), "spurious-question")
        self.assertEqual(self._score("settled", False, _contract()), "missed-question")
        self.assertEqual(self._score("unsettled", True, _contract()), "correct-ask")
        self.assertEqual(self._score("unsettled", False, needs_decision), "correct-ask")
        self.assertEqual(self._score("unsettled", False, _contract()), "missed-question")
        self.assertEqual(self._score("unsettled", False, None), "inconclusive")
        self.assertEqual(self._score("nonsense-case", False, cited), "inconclusive")

    def test_score_names_the_dangerous_cell(self) -> None:
        cited = _established([{"path": "docs/renewal.md", "quote": "rejected"}])
        # unsettled: the repository does not settle the oracle, the run neither
        # asked nor left it unresolved, and it told the reviewer the repository did.
        self.assertEqual(self._score("unsettled", False, cited), "unverified-claim")
        # An uncited repository-established claim is unverified in either case.
        self.assertEqual(self._score("unsettled", False, _established(None)), "unverified-claim")
        self.assertEqual(self._score("settled", False, _established([])), "unverified-claim")
        self.assertEqual(self._score("settled", True, _established(None)), "unverified-claim")

    def test_every_documented_label_is_reachable(self) -> None:
        self.assertEqual(len(set(self.eval.LABELS)), len(self.eval.LABELS))
        for label in self.eval.LABELS:
            self.assertIn(label, self.eval.__doc__)

    # -- confusion_matrix -------------------------------------------------

    def _result(self, case: str, label: str, asked: bool, **extra) -> dict:
        result = {"case": case, "score": label, "requested_human": asked,
                  "record": f"rec-{case}-{label}"}
        result.update(extra)
        return result

    def test_confusion_matrix_counts_the_four_cells(self) -> None:
        rendered = self.eval.confusion_matrix([
            self._result("settled", "correct-silent", False),
            self._result("settled", "correct-silent", False),
            self._result("settled", "spurious-question", True),
            self._result("unsettled", "correct-ask", True),
            self._result("unsettled", "unverified-claim", False),
        ])
        self.assertIn("5 of 5 recorded run(s) measured", rendered)
        settled = [line for line in rendered.splitlines() if "settled   (repo settles it)" in line]
        unsettled = [line for line in rendered.splitlines() if "unsettled (repo does not)" in line]
        self.assertEqual(settled[0].split()[-2:], ["1", "2"])
        self.assertEqual(unsettled[0].split()[-2:], ["1", "1"])
        self.assertIn("correct-silent         2", rendered)
        self.assertIn("dangerous cell", rendered)
        self.assertIn("not measured (0)", rendered)
        self.assertIn("none - every recorded run", rendered)

    def test_confusion_matrix_always_reports_what_was_not_measured(self) -> None:
        rendered = self.eval.confusion_matrix([
            self._result("settled", "correct-silent", False),
            {"record": "rec-broken", "case": "unsettled", "score": "inconclusive",
             "reason": "the review run could not be executed: claude not found"},
            {"record": "rec-empty", "case": "settled", "score": "inconclusive",
             "verdict": {"problems": ["no Intent Contract object in the record"]}},
            {"record": "rec-odd", "case": "settled", "score": "not-a-label"},
            {"record": "rec-case", "case": "half-settled", "score": "correct-ask"},
            "not even a dict",
        ])
        self.assertIn("1 of 6 recorded run(s) measured", rendered)
        self.assertIn("not measured (5)", rendered)
        self.assertIn("rec-case: unknown case: 'half-settled'", rendered)
        self.assertIn("claude not found", rendered)
        self.assertIn("no Intent Contract object in the record", rendered)
        self.assertIn("unknown label: 'not-a-label'", rendered)
        self.assertIn("result 5: the evaluation entry is not an object", rendered)
        self.assertIn("not passes", rendered)

    def test_confusion_matrix_bins_an_evaluation_that_predates_the_column_field(self) -> None:
        rendered = self.eval.confusion_matrix([
            {"record": "old", "case": "unsettled", "score": "correct-ask", "asked": False,
             "verdict": {"unresolved": 1}},
            {"record": "odd", "case": "settled", "score": "correct-silent",
             "verdict": "not an object"},
        ])
        self.assertIn("2 of 2 recorded run(s) measured", rendered)
        unsettled = [line for line in rendered.splitlines() if "unsettled (repo does not)" in line]
        settled = [line for line in rendered.splitlines() if "settled   (repo settles it)" in line]
        self.assertEqual(unsettled[0].split()[-2:], ["1", "0"])
        self.assertEqual(settled[0].split()[-2:], ["0", "1"])

    def test_confusion_matrix_flags_silent_runs_that_rendered_markdown_questions(self) -> None:
        rendered = self.eval.confusion_matrix([
            self._result("unsettled", "missed-question", False, markdown_fallback_seen=True),
        ])
        self.assertIn("advisory: 1 run(s)", rendered)
        self.assertNotIn(
            "advisory",
            self.eval.confusion_matrix([self._result("unsettled", "correct-ask", True)]),
        )

    def test_exit_code_never_passes_an_unmeasured_or_wrong_run(self) -> None:
        correct = [self._result("settled", "correct-silent", False),
                   self._result("unsettled", "correct-ask", True)]
        self.assertEqual(self.eval._exit_code(correct), 0)
        self.assertEqual(self.eval._exit_code([]), 1)
        self.assertEqual(self.eval._exit_code(
            correct + [{"score": "inconclusive", "reason": "no contract"}]), 1)
        self.assertEqual(self.eval._exit_code(
            [self._result("unsettled", "unverified-claim", False)]), 1)

    # -- record inputs ----------------------------------------------------

    def test_contract_is_recovered_from_the_kept_artifact_before_the_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / "20260724T000000Z-eval-settled-1"
            (record / "host-storage-abc/artifacts").mkdir(parents=True)
            transcript = _tool_use("Write", {
                "file_path": "/tmp/session/artifacts/intent-contract.draft.json",
                "content": json.dumps(_contract(status="from-transcript")),
            })
            (record / "transcript.jsonl").write_text(transcript + "\n", encoding="utf-8")

            document, source = self.eval.contract_from_record(record)
            self.assertEqual(source, "transcript")
            self.assertEqual(document["status"], "from-transcript")

            kept = record / "host-storage-abc/artifacts/intent-contract.draft.json"
            kept.write_text(json.dumps(_contract(status="from-artifact")), encoding="utf-8")
            document, source = self.eval.contract_from_record(record)
            self.assertEqual(source, "host-storage")
            self.assertEqual(document["status"], "from-artifact")

    def test_contract_from_transcript_ignores_other_writes_and_bad_json(self) -> None:
        lines = [
            _tool_use("Write", {"file_path": "/tmp/a/challenge-plan.json", "content": "{}"}),
            _tool_use("Write", {"file_path": "/tmp/a/intent-contract.draft.json",
                                "content": "{not json"}),
            _tool_use("Edit", {"file_path": "/tmp/a/intent-contract.draft.json"}),
        ]
        self.assertIsNone(self.eval.contract_from_transcript(lines))

    def test_evaluate_record_scores_a_record_without_running_anything(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / "20260724T000000Z-eval-unsettled-1"
            record.mkdir()
            (record / "transcript.jsonl").write_text("\n".join([
                _tool_use("AskUserQuestion", {"questions": [{"question": "Which boundary?"}]}),
                _tool_use("Write", {
                    "file_path": "/tmp/session/artifacts/intent-contract.draft.json",
                    "content": json.dumps(_contract(
                        status="needs-decision",
                        unresolved=[{"id": "UNR-001", "statement": "which boundary",
                                     "test_impact": "oracle"}])),
                }),
            ]) + "\n", encoding="utf-8")
            (record / "meta.json").write_text(json.dumps({"success": True, "exit_code": 0}))

            payload = self.eval.evaluate_record("unsettled", record, "eval-unsettled-1")
            self.assertEqual(payload["score"], "correct-ask")
            self.assertTrue(payload["asked"])
            self.assertTrue(payload["requested_human"])
            self.assertEqual(payload["contract_source"], "transcript")
            self.assertEqual(payload["verdict"]["unresolved"], 1)
            self.assertNotIn("reason", payload)

            written = self.eval.write_evaluation(record, payload)
            self.assertEqual(json.loads(written.read_text())["score"], "correct-ask")
            self.assertEqual(written.stat().st_mode & 0o777, 0o600)

    def test_evaluate_record_without_a_contract_is_inconclusive_with_a_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / "20260724T000000Z-eval-settled-1"
            record.mkdir()
            payload = self.eval.evaluate_record("settled", record, "eval-settled-1")
            self.assertEqual(payload["score"], "inconclusive")
            self.assertIn("transcript", payload["reason"])


class IntentEvalFixtureTest(unittest.TestCase):
    """The two fixtures must differ by exactly one sentence and nothing else."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.eval = load_module("devloop_intent_eval_fixtures", MODULE)

    def _git(self, repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
        ).stdout

    def test_only_the_settled_fixture_states_the_boundary_rule(self) -> None:
        sentence = self.eval.DECIDING_SENTENCE
        self.assertIn(sentence, self.eval.CASE_DOCS["settled"])
        self.assertNotIn(sentence, self.eval.CASE_DOCS["unsettled"])
        with tempfile.TemporaryDirectory() as directory:
            self.eval.loop.FIXTURES_DIR = Path(directory)
            settled = self.eval.build_case_fixture("settled", fresh=True)
            unsettled = self.eval.build_case_fixture("unsettled", fresh=True)

            for fixture, expected in ((settled, True), (unsettled, False)):
                tracked = self._git(fixture, "ls-files").split()
                self.assertIn("docs/renewal.md", tracked)
                body = "\n".join(
                    (fixture / name).read_text(encoding="utf-8") for name in tracked
                )
                self.assertEqual(sentence in body, expected, fixture.name)
                # Nothing else may settle the boundary: no test names it, and the
                # commit subjects are identical between the two fixtures.
                self.assertNotIn("end date equals", (fixture / "test_subscription.py").read_text())
                self.assertEqual(
                    self._git(fixture, "log", "--format=%s", "main..HEAD").strip(),
                    self.eval.HEAD_MESSAGE,
                )

            # Same diff shape in both cases.
            def diff(fixture: Path) -> str:
                return self._git(fixture, "diff", "main..HEAD")

            self.assertIn("subscription.end_date <= today", diff(settled))
            self.assertEqual(diff(settled), diff(unsettled))

    def test_fixtures_are_rebuildable_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.eval.loop.FIXTURES_DIR = Path(directory)
            first = self.eval.build_case_fixture("settled", fresh=True)
            head = self._git(first, "rev-parse", "HEAD").strip()
            (first / "docs/renewal.md").write_text("tampered\n", encoding="utf-8")
            reused = self.eval.build_case_fixture("settled")
            self.assertEqual((reused / "docs/renewal.md").read_text(), "tampered\n")
            rebuilt = self.eval.build_case_fixture("settled", fresh=True)
            self.assertEqual(self._git(rebuilt, "rev-parse", "HEAD").strip(), head)
            self.assertIn(self.eval.DECIDING_SENTENCE,
                          (rebuilt / "docs/renewal.md").read_text(encoding="utf-8"))
            settings = json.loads((rebuilt / ".claude/settings.json").read_text())
            self.assertEqual(settings, self.eval.loop.FIXTURE_SETTINGS)

    def test_unknown_case_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            self.eval.build_case_fixture("../escape")


if __name__ == "__main__":
    unittest.main()
