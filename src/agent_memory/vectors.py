import numpy as np


def as_array(vector):
    if hasattr(vector, "to_numpy"):
        vector = vector.to_numpy()
    return np.asarray(vector, dtype=np.float32).reshape(-1)


def vector_stats(vector, include_values=True):
    values = as_array(vector)
    if not values.size:
        return None
    stats = {
        "dimensions": int(values.size),
        "norm": round(float(np.linalg.norm(values)), 6),
        "mean": round(float(values.mean()), 6),
        "std": round(float(values.std()), 6),
        "min": round(float(values.min()), 6),
        "max": round(float(values.max()), 6),
        "nonzero": int(np.count_nonzero(values)),
    }
    if include_values:
        stats["values"] = [round(float(value), 5) for value in values]
    return stats


def cosine(left, right):
    if left is None or right is None:
        return None
    a, b = as_array(left), as_array(right)
    if not a.size or a.shape != b.shape:
        return None
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator == 0:
        return None
    return round(float(np.dot(a, b) / denominator), 5)


def project(vectors):
    empty = {"method": "pca", "explained": [], "coordinates": []}
    if isinstance(vectors, np.ndarray) and vectors.ndim == 2:
        matrix = vectors.astype(np.float32, copy=False)
    else:
        rows = [as_array(vector) for vector in vectors]
        if not rows:
            return empty
        try:
            matrix = np.stack(rows)
        except ValueError:
            return empty
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 2:
        return empty
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    try:
        left, singular, _ = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError:
        return empty
    coordinates = left[:, :2] * singular[:2]
    for axis in range(coordinates.shape[1]):
        pivot = int(np.argmax(np.abs(coordinates[:, axis])))
        if coordinates[pivot, axis] < 0:
            coordinates[:, axis] *= -1
    variance = singular**2
    total = float(variance.sum())
    explained = ([round(float(value / total), 5) for value in variance[:2]]
                 if total else [0.0, 0.0])
    span = float(np.max(np.abs(coordinates))) or 1.0
    normalized = 0.5 + 0.42 * coordinates / span
    normalized[:, 1] = 1.0 - normalized[:, 1]
    return {
        "method": "pca",
        "explained": explained,
        "coordinates": [[round(float(x), 5), round(float(y), 5)]
                        for x, y in normalized],
    }
