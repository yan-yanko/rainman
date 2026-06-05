"""
Keyword-Based Sentiment Classifier
====================================

Zero-cost, zero-latency sentiment tagging for memory entries.
Ported from CogniTrait emotions.py — added "frustrated" category
for developer context (bugs, blockers, regressions).

No LLM calls. Accuracy is sufficient for retrieval modulation.
"""

from typing import Set


_POSITIVE_WORDS: Set[str] = {
    "happy", "great", "excellent", "wonderful", "love", "loved", "enjoy",
    "enjoyed", "amazing", "fantastic", "proud", "success", "successful",
    "win", "won", "celebrate", "grateful", "thankful", "excited", "joy",
    "pleased", "delighted", "thrilled", "accomplished", "achievement",
    "reward", "rewarding", "beautiful", "perfect", "brilliant", "outstanding",
    "superb", "impressive", "satisfied", "works", "working", "solved",
    "fixed", "shipped", "deployed", "validated", "confirmed", "passed",
}

_NEGATIVE_WORDS: Set[str] = {
    "bad", "terrible", "awful", "horrible", "hate", "hated", "dislike",
    "fail", "failed", "failure", "loss", "lost", "worst", "poor",
    "disappointed", "disappointing", "regret", "mistake", "wrong",
    "broken", "ruined", "destroyed", "painful", "rejected", "rejection",
    "ugly", "miserable", "dreadful", "pathetic", "useless", "crash",
    "crashed", "crashes", "crashing", "corrupt", "corrupted", "vulnerability",
    "insecure", "bug", "bugs", "error", "errors",
}

_ANXIOUS_WORDS: Set[str] = {
    "worried", "worry", "anxious", "anxiety", "nervous", "scared",
    "fear", "feared", "panic", "panicked", "dread", "uncertain",
    "uneasy", "tense", "tension", "stress", "stressed", "stressful",
    "overwhelmed", "apprehensive", "insecure", "doubt", "doubtful",
    "risky", "risk", "fragile", "unstable", "flaky", "intermittent",
}

_FRUSTRATED_WORDS: Set[str] = {
    "frustrated", "frustrating", "frustration", "annoyed", "annoying",
    "angry", "anger", "furious", "rage", "irritated", "aggravated",
    "stuck", "blocked", "blocker", "impossible", "wasted", "waste",
    "regression", "regressed", "reverted", "undo", "undone", "again",
    "still", "yet", "another", "workaround", "hack", "kludge",
    "technical debt", "debt", "spaghetti", "mess", "nightmare",
}

_EXCITED_WORDS: Set[str] = {
    "excited", "exciting", "excitement", "thrilled", "thrilling",
    "eager", "enthusiastic", "pumped", "stoked", "anticipation",
    "energized", "inspired", "inspiring", "motivated", "passionate",
    "breakthrough", "eureka", "discovered", "insight", "idea",
    "prototype", "demo", "launch", "release", "milestone",
}


def classify_sentiment(content: str) -> str:
    """
    Classify the dominant sentiment in text content.

    Returns one of: positive, negative, neutral, anxious, frustrated, excited.

    Uses keyword overlap counting. Ties broken by specificity
    (frustrated/anxious/excited are more specific than positive/negative).
    """
    words = set(content.lower().split())

    scores = {
        "frustrated": len(words & _FRUSTRATED_WORDS),
        "anxious":    len(words & _ANXIOUS_WORDS),
        "excited":    len(words & _EXCITED_WORDS),
        "positive":   len(words & _POSITIVE_WORDS),
        "negative":   len(words & _NEGATIVE_WORDS),
    }

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "neutral"
    return best
