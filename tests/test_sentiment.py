"""Tests for keyword-based sentiment classifier."""

import pytest
from rainman.core.sentiment import classify_sentiment


@pytest.mark.unit
class TestSentimentClassifier:

    def test_positive_content(self):
        assert classify_sentiment("Great success! The feature shipped and works perfectly") == "positive"

    def test_negative_content(self):
        assert classify_sentiment("Terrible failure, the build crashed and everything is broken") == "negative"

    def test_neutral_content(self):
        assert classify_sentiment("Updated the config file with new settings") == "neutral"

    def test_frustrated_content(self):
        assert classify_sentiment("Frustrated with this regression, stuck on the same blocker again") == "frustrated"

    def test_anxious_content(self):
        assert classify_sentiment("Worried about the risk, this feels fragile and unstable") == "anxious"

    def test_excited_content(self):
        assert classify_sentiment("Excited about this breakthrough! Inspired to build the prototype") == "excited"

    def test_empty_string(self):
        assert classify_sentiment("") == "neutral"

    def test_specificity_wins_over_general(self):
        # "frustrated" is more specific than "negative"
        assert classify_sentiment("frustrated and annoyed with this terrible hack workaround") == "frustrated"

    def test_developer_positive_terms(self):
        assert classify_sentiment("The tests passed and the fix was deployed successfully") == "positive"

    def test_developer_negative_terms(self):
        assert classify_sentiment("Found a vulnerability in the corrupted database") == "negative"
