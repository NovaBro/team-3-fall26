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
import os
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


# One set of example sentences per health goal: "fits" vs "doesn't fit".
GOAL_ANCHORS = {
    "weight-loss": (
        (
            "light, low-calorie meal",
            "small portions with lots of vegetables",
            "salad with lean protein and dressing on the side",
            "grilled fish with steamed vegetables",
        ),
        (
            "huge, heavy portions",
            "rich, creamy and cheesy dishes",
            "fried food and big desserts",
        ),
    ),
    "muscle-gain": (
        (
            "high-protein meal with grilled chicken",
            "lean steak and eggs packed with protein",
            "protein bowl with chicken, rice and beans",
            "generous portions of meat and fish",
        ),
        (
            "mostly bread, pastries and sweets",
            "small snack with little protein",
            "sugary drinks and desserts",
            "mostly rice and vegetables with very little meat",
        ),
    ),
    "heart-health": (
        (
            "grilled fish with olive oil and vegetables",
            "fresh dishes that are not fried and not too salty",
            "whole grains, beans and greens",
            "roasted vegetables with lentils and beans",
            "seasoned with herbs and lemon instead of salt",
        ),
        (
            "very salty, greasy fried food",
            "fatty processed meats like bacon and sausage",
            "heavy butter and cream sauces",
        ),
    ),
    "less-sugar": (
        (
            "savory dishes and unsweetened drinks",
            "fresh fruit instead of dessert",
            "simple savory meals without sweet sauces",
            "unsweetened tea and sparkling water",
        ),
        (
            "sugary desserts, cakes and donuts",
            "sweet sauces, syrup and soda",
            "very sweet bubble tea and milkshakes",
        ),
    ),
    "balanced-diet": (
        (
            "balanced plate with vegetables, protein and whole grains",
            "a variety of fresh, wholesome dishes",
            "rice, vegetables and lean meat in one meal",
        ),
        (
            "only fried snacks and sweets",
            "fast food burger and fries",
            "just dessert and sugary drinks",
        ),
    ),
    "low-carb": (
        (
            "lettuce wrap with no bun",
            "grilled meat and vegetables without rice or bread",
            "cauliflower rice and keto-friendly options",
            "protein and vegetables without bread, rice or noodles",
        ),
        (
            "big bowl of pasta with bread",
            "lots of rice, noodles and pizza",
            "pastries, bagels and sweet drinks",
            "burger on a bun with fries",
        ),
    ),
}


def _sigmoid_scores(sims, n_good):
    good = sims[:, :n_good].max(axis=1)
    bad = sims[:, n_good:].max(axis=1)
    scores = []
    for g, b in zip(good, bad):
        if max(g, b) < RELEVANCE_MIN:
            scores.append(None)
        else:
            scores.append(1.0 / (1.0 + math.exp(-(g - b) / TEMPERATURE)))
    return scores


def _shrunk(scores):
    used = [s for s in scores if s is not None]
    if not used:
        return None, 0
    score = (sum(used) + 0.5 * PRIOR_SENTENCES) / (len(used) + PRIOR_SENTENCES)
    return round(score, 4), len(used)


def all_scores(texts, encoder):
    """General health score plus one score per health goal, in one pass.

    Returns (health, sentences used, {goal: score}). Each sentence is turned
    into numbers once and compared with every anchor set. A goal with no
    related sentence is left out of the dict; health is None when no sentence
    is about food health.
    """
    sentences = []
    for text in texts:
        sentences.extend(split_sentences(text))
    sentences = sentences[:MAX_SENTENCES]
    if not sentences:
        return None, 0, {}
    sets = [(HEALTHY_ANCHORS, UNHEALTHY_ANCHORS)] + list(GOAL_ANCHORS.values())
    anchors = [a for good, bad in sets for a in list(good) + list(bad)]
    vectors = _unit_rows(encoder(anchors + sentences))
    n_anchors = len(anchors)
    anchor_vecs, sent_vecs = vectors[:n_anchors], vectors[n_anchors:]
    results, start = [], 0
    for good, bad in sets:
        end = start + len(good) + len(bad)
        sims = sent_vecs @ anchor_vecs[start:end].T
        results.append(_shrunk(_sigmoid_scores(sims, len(good))))
        start = end
    health, used = results[0]
    goals = {
        goal: score
        for goal, (score, _n) in zip(GOAL_ANCHORS, results[1:])
        if score is not None
    }
    return health, used, goals


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


FASTEMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def load_encoder(model_name=MODEL_NAME, backend="auto"):
    """Return an encoder (list of strings -> 2-D array) for ``model_name``.

    backend "fastembed": the same MiniLM model run with ONNX Runtime (small;
    installed from requirements.txt, so it also runs on the server).
    backend "sentence-transformers": PyTorch (heavy; requirements-ml.txt).
    backend "auto": fastembed if installed, else sentence-transformers.
    """
    if backend in ("auto", "fastembed"):
        try:
            return _fastembed_encoder(model_name)
        except ImportError:
            if backend == "fastembed":
                raise RuntimeError(
                    "fastembed is not installed. Run: pip install -r requirements.txt"
                )
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - depends on local setup
        raise RuntimeError(
            "No encoder installed. Run: pip install -r requirements.txt"
        ) from exc
    model = SentenceTransformer(model_name)

    def encode(texts):
        return model.encode(list(texts), batch_size=64, show_progress_bar=False)

    return encode


def _fastembed_encoder(model_name):
    from fastembed import TextEmbedding  # ImportError -> caller falls back

    name = model_name if "/" in model_name else f"sentence-transformers/{model_name}"
    model = TextEmbedding(name, cache_dir=os.environ.get("FASTEMBED_CACHE_PATH"))

    def encode(texts):
        return np.array(list(model.embed(list(texts), batch_size=64)))

    return encode
