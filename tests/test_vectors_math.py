import numpy as np

from agent_memory.vectors import cosine, project, vector_stats


def test_vector_stats_and_cosine_are_bounded():
    vector = np.array([3.0, 4.0, 0.0], dtype=np.float32)
    stats = vector_stats(vector)
    assert stats["dimensions"] == 3
    assert stats["norm"] == 5.0
    assert stats["values"] == [3.0, 4.0, 0.0]
    assert stats["nonzero"] == 2
    assert cosine(vector, vector) == 1.0
    assert cosine(vector, [0.0, 0.0, 0.0]) is None
    assert cosine(vector, [1.0, 2.0]) is None
    assert cosine(None, vector) is None
    assert vector_stats([]) is None


def test_projection_is_normalized_explained_and_deterministic():
    rng = np.random.default_rng(7)
    vectors = rng.normal(size=(8, 16)).astype(np.float32)
    result = project(vectors)
    assert result["method"] == "pca"
    assert len(result["coordinates"]) == 8
    assert len(result["explained"]) == 2
    assert 0.0 <= result["explained"][1] <= result["explained"][0] <= 1.0
    assert all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in result["coordinates"])
    assert project(vectors) == result
    assert project(vectors[:1])["coordinates"] == []


def test_projection_handles_degenerate_sets():
    same = project(np.ones((4, 8), dtype=np.float32))
    assert same["coordinates"] == [[0.5, 0.5]] * 4
    assert same["explained"] == [0.0, 0.0]
    assert project([])["coordinates"] == []
