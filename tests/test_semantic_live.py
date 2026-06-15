"""
LIVE semantic-lane tests — exercise the real local embedding model (M7).

Skipped automatically unless the ``rainman[semantic]`` extra (model2vec) is
installed, so the default zero-dep CI never runs or needs it. Where it IS
installed, this proves the lane works end-to-end with a real model: synonyms
separate from unrelated text, and recall surfaces a synonym match that pure
lexical retrieval misses.
"""

import os

import pytest

pytest.importorskip("model2vec")  # whole module skipped without the extra

from rainman.core.engine import RainmanEngine  # noqa: E402
from rainman.semantic import cosine, load_provider  # noqa: E402


@pytest.fixture(scope="module")
def provider():
    p = load_provider()
    if p is None:
        pytest.skip("no semantic provider available")
    return p


@pytest.fixture
def engine(tmp_path):
    project = str(tmp_path / "project")
    global_dir = str(tmp_path / "global")
    os.makedirs(project)
    os.makedirs(global_dir)
    e = RainmanEngine(project_dir=project, global_dir=global_dir)
    e.store.init_project(project)
    e.store.init_global()
    return e


@pytest.mark.unit
class TestLiveSemantic:

    def test_provider_loads(self, provider):
        assert provider.name.startswith("model2vec")

    def test_synonyms_separate_from_unrelated(self, provider):
        syn = cosine(*provider.embed([
            "how do I validate the auth token",
            "verify the login credential signature",
        ]))
        unrel = cosine(*provider.embed([
            "how do I validate the auth token",
            "css grid flexbox layout spacing",
        ]))
        assert syn > unrel
        # Synonym similarity clears the calibrated floor; unrelated stays well below.
        assert syn >= 0.15
        assert unrel < 0.15

    def test_recall_surfaces_synonym_that_lexical_misses(self, provider, engine):
        engine.add("the login flow checks the session credential before charging",
                   category="note")
        engine.add("notes on the css grid spacing and dark-mode palette",
                   category="note")

        # Pure lexical: "authenticate" shares no stem with "login/credential" ->
        # both fail the relevance floor -> nothing surfaces.
        assert engine.recall("how do I authenticate a user") == []

        # Semantic lane: the login memory is surfaced via dense similarity.
        results = engine.recall("how do I authenticate a user",
                                semantic_provider=provider)
        contents = [r.memory.content for r in results]
        assert any("login flow" in c for c in contents)
        assert not any("css grid" in c for c in contents)
