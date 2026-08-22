import embedding


def test_cosine_similarity_identical():
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    assert embedding.cosine_similarity(a, b) == 1.0


def test_cosine_similarity_orthogonal():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert embedding.cosine_similarity(a, b) == 0.0


def test_cosine_similarity_zero_vector():
    assert embedding.cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_get_embedding_returns_384_dim_list():
    vec = embedding.get_embedding("hello world")
    assert isinstance(vec, list)
    assert len(vec) == embedding.EMBEDDING_DIM
    assert all(isinstance(v, float) for v in vec)


def test_get_embedding_empty_returns_zero_vector():
    vec = embedding.get_embedding("")
    assert len(vec) == embedding.EMBEDDING_DIM
    assert all(v == 0.0 for v in vec)
