"""Tests for the associative-graph upgrade: real linking (M3) + spreading
activation (M4)."""

import os
import time

import pytest

from rainman.core.engine import RainmanEngine
from rainman.core.models import Memory
from rainman.core.scoring import associative_score, build_reverse_link_index


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


def _mem(mid, content="x", **kw):
    return Memory(id=mid, content=content, timestamp=time.time(), importance=0.5, **kw)


@pytest.mark.unit
class TestRealLinking:
    """M3: stemmed, windowless, typed-edge linking."""

    def test_links_across_the_old_100_window(self, engine):
        first = engine.add("rate limiter token bucket algorithm for the gateway")
        # Push the first memory well past the old last-100 window.
        for i in range(110):
            engine.add(f"unrelated filler memory number {i} about miscellany")
        related = engine.add("the gateway token bucket rate limiter needed tuning")
        assert first.id in related.linked_ids  # would have been missed by the window

    def test_stemmed_linking(self, engine):
        a = engine.add("the authentication module validates bearer tokens")
        b = engine.add("authenticating a user requires a valid bearer token")
        assert a.id in b.linked_ids  # authentication/authenticating -> same stem

    def test_shared_file_ref_creates_edge(self, engine):
        a = engine.add("totally distinct subject matter here about widgets",
                       file_refs=["src/payments/charge.py"])
        b = engine.add("a completely different topic concerning sprockets",
                       file_refs=["src/payments/charge.py"])
        assert a.id in b.linked_ids  # linked by shared file, not content

    def test_shared_tag_creates_edge(self, engine):
        a = engine.add("first note on one subject entirely", tags=["billing"])
        b = engine.add("second note on a different subject", tags=["billing"])
        assert a.id in b.linked_ids


@pytest.mark.unit
class TestSpreadingActivation:
    """M4: 2-hop spreading activation with decay + trust gating."""

    def _graph(self):
        # m3 -> m2 -> m1 (chain). m1 is the anchor (a top result).
        m1 = _mem("m1")
        m2 = _mem("m2", linked_ids=["m1"])
        m3 = _mem("m3", linked_ids=["m2"])
        entries = [m1, m2, m3]
        rev = build_reverse_link_index(entries)
        fwd = {m.id: set(m.linked_ids) for m in entries}
        return entries, rev, fwd

    def test_one_hop_boost(self):
        entries, rev, fwd = self._graph()
        s = associative_score("m2", entries, ["m1"], reverse_index=rev,
                              forward_index=fwd, max_hops=2)
        assert s == pytest.approx(0.3)

    def test_two_hop_decayed_boost(self):
        entries, rev, fwd = self._graph()
        s2 = associative_score("m2", entries, ["m1"], reverse_index=rev,
                              forward_index=fwd, max_hops=2)
        s3 = associative_score("m3", entries, ["m1"], reverse_index=rev,
                              forward_index=fwd, max_hops=2)
        # m3 is 2 hops from the anchor: boosted, but less than the 1-hop m2.
        assert 0.0 < s3 < s2
        assert s3 == pytest.approx(0.15)  # 0.3 * decay(0.5)

    def test_two_hop_disabled_at_max_hops_1(self):
        entries, rev, fwd = self._graph()
        s3 = associative_score("m3", entries, ["m1"], reverse_index=rev,
                              forward_index=fwd, max_hops=1)
        assert s3 == 0.0  # original direct-neighbour behavior

    def test_two_hop_respects_trust_gate(self):
        entries, rev, fwd = self._graph()
        # Anchor m1 is strictly MORE trusted than entry m3 -> boost can't flow.
        trust_index = {"m1": 3, "m2": 1, "m3": 1}
        s3 = associative_score("m3", entries, ["m1"], reverse_index=rev,
                              forward_index=fwd, trust_index=trust_index, max_hops=2)
        assert s3 == 0.0
