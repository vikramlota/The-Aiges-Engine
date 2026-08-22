"""
Optional transformer-based enrichment: auto-detects which ASCI
expert-review categories (health claims, automotive claims, etc.) a
caption's text plausibly touches on, so content_categories doesn't rely
purely on a human remembering to tag it by hand.

Deliberately kept OUT of engine.py / rules.py, which stay pure stdlib and
fast to test. Importing THIS module pulls in `transformers` and a
~0.2-0.4B parameter model -- opt into it only where you actually want
auto-tagging (an ingestion pipeline), not as a hard dependency of the core
rule engine.

IMPORTANT -- what this module is and isn't:
This only ever ADDS a category tag for a human/expert to review, exactly
like manually setting content_categories=[...] would. It never decides
FLAGGED / COMPLIANT / NEEDS EXPERT REVIEW on its own -- audit_post still
does that, and it still never auto-verifies a health or automotive claim.
Getting a category tag wrong here means, at worst, a post gets routed to
a human that didn't strictly need it (mildly wasteful), or misses one that
did (why you should still spot-check results, especially early on). It
can't silently mis-clear a real violation, because this module never
makes a compliance verdict at all -- only a "does this deserve a second
pair of eyes" suggestion.
"""

# Candidate categories this model can plausibly judge from caption text
# alone. Left out on purpose:
#   - celebrity_due_diligence: about the endorser's real relationship to
#     the product, not something caption phrasing reveals.
#   - surrogate_advertising, general_truthfulness: too broad or too
#     context-dependent (brand identity, overall impression) for a single
#     caption-level label to mean much. Pretending a caption classifier
#     can judge these would be exactly the false precision this project
#     is built to avoid -- they still need a human to tag manually.
CANDIDATE_CATEGORIES = {
    "health_wellness_claims": "a health, medical, or wellness claim such as curing, treating, or healing something",
    "food_beverage_claims": "a nutrition or health claim about a food or beverage product",
    "educational_institutions": "a claim about a course, degree, accreditation, or job placement from an educational institution",
    "automotive_claims": "a safety, performance, or mileage claim about a vehicle",
    "awards_rankings_claims": "a claimed award, ranking, or being the number one choice",
    "children_targeted": "content clearly aimed at or featuring children as the audience",
}

DEFAULT_MODEL = "facebook/bart-large-mnli"
# Worth trying if a lot of your captions mix Hindi/English/regional
# languages, since this one is trained for multilingual zero-shot:
# "MoritzLaurer/ModernBERT-large-zeroshot-v2.0"

_classifier = None  # lazy-loaded: importing this module should not, by
                     # itself, trigger a multi-hundred-MB model download
_classifier_unavailable = False  # remembers a failed load so a bad
                                   # connection doesn't retry-and-timeout on
                                   # every single post in a batch


def _get_classifier(model_name: str = DEFAULT_MODEL):
    global _classifier, _classifier_unavailable
    if _classifier_unavailable:
        raise RuntimeError("claim classifier previously failed to load; not retrying this run")
    if _classifier is None:
        from transformers import pipeline
        _classifier = pipeline("zero-shot-classification", model=model_name)
    return _classifier


def classify_content_categories(caption: str, threshold: float = 0.6, model_name: str = DEFAULT_MODEL) -> list:
    """
    Returns a list of ASCI category keys (matching rules.ASCI_CATEGORIES)
    whose candidate description scores at or above `threshold` against
    this caption, using multi-label zero-shot classification (a caption
    can touch zero, one, or several categories at once -- this isn't a
    forced single pick).

    Fails closed, not open: returns [] on any problem (transformers not
    installed, model won't load, empty caption, an error mid-inference)
    rather than raising. Callers should treat an empty result exactly like
    "nothing auto-detected, fall back to manual tagging" -- never as
    "confirmed clean," since a false negative here just means a human
    still needs to catch it by hand, same as before this module existed.
    """
    global _classifier_unavailable
    if not caption or not caption.strip():
        return []

    try:
        classifier = _get_classifier(model_name)
    except Exception as e:
        if not _classifier_unavailable:
            print(f"    [!] Claim classifier unavailable ({e}) -- disabling auto-detection for the rest of this run.")
            _classifier_unavailable = True
        return []

    labels = list(CANDIDATE_CATEGORIES.values())
    try:
        result = classifier(caption, candidate_labels=labels, multi_label=True)
    except Exception as e:
        print(f"    [!] Claim classifier failed on this caption ({e}) -- skipping auto-detection for it.")
        return []

    label_to_key = {v: k for k, v in CANDIDATE_CATEGORIES.items()}
    return [
        label_to_key[label]
        for label, score in zip(result["labels"], result["scores"])
        if score >= threshold
    ]