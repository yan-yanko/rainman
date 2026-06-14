"""Tests for the write-side salience filter (M6)."""

import pytest

from rainman.core.salience import salience_score, is_salient, SALIENCE_THRESHOLD


@pytest.mark.unit
class TestSalience:

    def test_failure_is_always_salient(self):
        assert is_salient("failure", "the build broke")
        assert salience_score("failure", "x") >= 0.6

    def test_solution_is_always_salient(self):
        assert is_salient("solution", "applied the patch")

    def test_plain_read_of_boring_file_is_dropped(self):
        # A note with no error/security/intent/build signal scores 0 -> dropped.
        score = salience_score("note", "File utils/format.py: def to_title(s):", ["utils/format.py"])
        assert score < SALIENCE_THRESHOLD
        assert not is_salient("note", "File utils/format.py: def to_title(s):", ["utils/format.py"])

    def test_security_path_note_is_salient(self):
        assert is_salient("note", "File services/auth.py: def login(u):", ["services/auth.py"])

    def test_error_content_note_is_salient(self):
        assert is_salient("note", "File x.py: raised a TypeError exception on null input", ["x.py"])

    def test_intent_signal_note_is_salient(self):
        assert is_salient("note", "File x.py: # TODO fix the race condition here", ["x.py"])

    def test_build_command_outcome_is_salient(self):
        assert is_salient("note", "Command succeeded: pytest -q", [], "pytest -q tests/")

    def test_score_is_capped_at_one(self):
        s = salience_score("failure", "error exception todo auth", ["deploy.yml"], "pytest")
        assert s <= 1.0
