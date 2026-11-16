"""AI health score from review and menu text (no training needed).

How it works, step by step:
1. A pre-trained sentence-embedding model turns any sentence into a list of
   numbers (a "vector"). Sentences with similar meaning get similar vectors.
2. We write a few short example sentences ("anchors") that describe healthy
   food and a few that describe unhealthy food.
3. For every sentence in a restaurant's reviews or menu we check how close it
   is to the closest healthy anchor and to the closest unhealthy anchor
   (cosine similarity, 1 = same meaning). Closer to healthy -> score near 1,
   closer to unhealthy -> near 0. Sentences about other things (service,
   parking, ...) are far from every anchor and are skipped.
4. The restaurant score is the average sentence score, pulled toward 0.5 when
   there are only a few sentences, so one sentence can't decide everything.

The model runs only on a developer machine (`python manage.py score_health`).
The results are stored in ``community.HealthScore`` and the web server just
reads them, so the server never needs the model or its large packages.
"""

from __future__ import annotations

import math
import re

import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

HEALTHY_ANCHORS = (
    "fresh salad with lots of vegetables",
    "grilled fish and steamed vegetables",
    "healthy, light and nutritious meal",
    "vegan bowl with whole grains and greens",
    "lean grilled chicken with brown rice",
    "fresh fruit, smoothies and low-calorie options",
    "organic, wholesome food made with fresh ingredients",
)
UNHEALTHY_ANCHORS = (
    "greasy fried food",
    "deep-fried chicken and french fries",
    "heavy, oily and very salty dishes",
    "sugary desserts, donuts and soda",
    "huge portions of cheesy, fatty comfort food",
    "processed fast food burgers",
)

# A sentence must be at least this close to some anchor to count.
RELEVANCE_MIN = 0.30
# Smaller = sharper split between healthy and unhealthy sentences.
TEMPERATURE = 0.05
# "Pretend" neutral sentences added to every restaurant (shrinks small samples).
PRIOR_SENTENCES = 3
# Cap per restaurant so a huge menu doesn't take forever.
MAX_SENTENCES = 80

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def split_sentences(text):
    """Split review/menu text into short sentences worth scoring."""
    parts = _SENTENCE_SPLIT.split(text or "")
    return [p.strip() for p in parts if len(p.strip().split()) >= 2]


def _unit_rows(matrix):
    matrix = np.asarray(matrix, dtype=float)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def sentence_scores(sentences, encoder):
    """0–1 health score per sentence, or None when it isn't about food health.

    ``encoder`` turns a list of strings into a 2-D array (one row per string).
    """
    sentences = list(sentences)
    if not sentences:
        return []
    anchors = list(HEALTHY_ANCHORS) + list(UNHEALTHY_ANCHORS)
    vectors = _unit_rows(encoder(anchors + sentences))
    n_anchors = len(anchors)
    n_healthy = len(HEALTHY_ANCHORS)
    anchor_vecs, sent_vecs = vectors[:n_anchors], vectors[n_anchors:]
    sims = sent_vecs @ anchor_vecs.T  # cosine similarity, shape (sentences, anchors)
    healthy = sims[:, :n_healthy].max(axis=1)
    unhealthy = sims[:, n_healthy:].max(axis=1)

    scores = []
    for h, u in zip(healthy, unhealthy):
        if max(h, u) < RELEVANCE_MIN:
            scores.append(None)
            continue
        scores.append(1.0 / (1.0 + math.exp(-(h - u) / TEMPERATURE)))
    return scores


def restaurant_score(texts, encoder):
    """(score 0–1, sentences used) for one restaurant's reviews + menu text.

    Returns (None, 0) when no sentence is about food health.
    """
    sentences = []
    for text in texts:
        sentences.extend(split_sentences(text))
    sentences = sentences[:MAX_SENTENCES]
    used = [s for s in sentence_scores(sentences, encoder) if s is not None]
    if not used:
        return None, 0
    score = (sum(used) + 0.5 * PRIOR_SENTENCES) / (len(used) + PRIOR_SENTENCES)
    return round(score, 4), len(used)


def load_encoder(model_name=MODEL_NAME):
    """Return an encoder backed by sentence-transformers (local use only).

    Install once on your Mac: pip install -r requirements-ml.txt
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - depends on local setup
        raise RuntimeError(
            "sentence-transformers is not installed. "
            "Run: pip install -r requirements-ml.txt"
        ) from exc
    model = SentenceTransformer(model_name)

    def encode(texts):
        return model.encode(list(texts), batch_size=64, show_progress_bar=False)

    return encode
