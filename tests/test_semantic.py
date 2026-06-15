"""Tests for the optional semantic lane seam (M7): RRF fusion, provider
protocol, and the synonym-recall gain — all proven with a stub provider, no
model dependency."""

import os

import pytest

from rainman.core.engine import RainmanEngine
from rainman.core.fusion import reciprocal_rank_fusion
from rainman.semantic import cosine, load_provider, SemanticProvider


class StubProvider:
    """Deterministic concept-vector embedder. Maps synonyms to the same axis so
    we can prove the semantic lane closes the lexical gap, with no real model."""

    name = "stub"
    CONCEPTS = {
        "auth": 0, "authentication": 0, "authenticate": 0, "login": 0,
        "signin": 0, "credential": 0, "session": 0,
        "database": 1, "db": 1, "postgres": 1, "sql": 1, "query": 1,
        "cache": 2, "redis": 2, "memcached": 2, "caching": 2,
    }

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0, 0.0, 0.0, 0.0]
            tl = t.lower()
            for word, dim in self.CONCEPTS.items():
                if word in tl:
                    v[dim] += 1.0
            if sum(v) == 0.0:
                v[3] = 1.0  # "other" axis so the vector has a nonzero norm
            out.append(v)
        return out


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
class TestFusion:

    def test_single_ranking_preserves_order(self):
        fused = reciprocal_rank_fusion([["a", "b", "c"]])
        assert fused["a"] > fused["b"] > fused["c"]

    def test_two_rankings_fuse(self):
        # 'b' is top of the second ranking and 2nd of the first -> should beat
        # 'c' which is only ever mid/low.
        fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "c"]])
        ordered = sorted(fused, key=lambda k: fused[k], reverse=True)
        assert ordered[0] in ("a", "b")
        assert ordered[-1] == "c"


@pytest.mark.unit
class TestProviderSeam:

    def test_loader_matches_extra_availability(self):
        # Loader returns a provider iff a backend is importable; None otherwise.
        import importlib.util
        has_backend = importlib.util.find_spec("model2vec") is not None
        provider = load_provider()
        if has_backend:
            assert provider is not None
            assert isinstance(provider, SemanticProvider)
        else:
            assert provider is None

    def test_default_engine_has_no_provider(self, engine):
        assert engine._get_semantic_provider() is None

    def test_stub_satisfies_protocol(self):
        assert isinstance(StubProvider(), SemanticProvider)

    def test_cosine_basic(self):
        assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
        assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)


@pytest.mark.unit
class TestSemanticRecall:

    def test_lexical_misses_synonym(self, engine):
        # "login" never shares a stem with "authentication" -> pure lexical misses.
        engine.add("the user login flow validates the active session token")
        engine.add("notes about the css grid layout and spacing rules")
        plain = engine.recall("authentication")
        assert plain == []  # the synonym gap, with no semantic lane

    def test_semantic_lane_surfaces_synonym_match(self, engine):
        engine.add("the user login flow validates the active session token")
        engine.add("notes about the css grid layout and spacing rules")
        results = engine.recall("authentication", semantic_provider=StubProvider())
        # The login memory is surfaced via dense similarity; the css note is not.
        contents = [r.memory.content for r in results]
        assert any("login flow" in c for c in contents)
        assert not any("css grid" in c for c in contents)

    def test_no_provider_is_unchanged(self, engine):
        engine.add("redis caching strategy for the session store")
        with_default = engine.recall("redis caching")
        # No provider wired -> ordinary lexical recall still works.
        assert any("redis" in r.memory.content for r in with_default)
