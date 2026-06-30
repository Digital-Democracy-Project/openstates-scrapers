import logging
import re
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

_config = yaml.safe_load(
    (Path(__file__).parent / "config" / "motion_classification.yaml").read_text()
)

_PREPROCESSORS = {
    "strip_sequence_number": lambda t: re.sub(r"\s*\(#\d+\)\s*$", "", t),
}

# Exact jurisdiction keys expected by scrapers — asserted in the test suite.
KNOWN_JURISDICTIONS = frozenset(_config["jurisdictions"].keys())


def classify_motion(jurisdiction: str, motion_text: str, bill_action: str = None) -> list:
    """Return an OpenStates motion_classification list for a vote event.

    Args:
        jurisdiction: Two-letter key matching a jurisdictions entry in
                      config/motion_classification.yaml (e.g. "us", "az").
        motion_text:  The raw motion text from the legislature source.
        bill_action:  Optional secondary field used by Virginia to distinguish
                      committee-passage from floor-passage via the
                      LegislationActionDescription field.

    Returns:
        A list such as ["passage"], ["committee-passage"], or [].
        Unknown jurisdictions log a warning and return [].
    """
    cfg = _config["jurisdictions"].get(jurisdiction)
    if cfg is None:
        logger.warning("classify_motion: unknown jurisdiction %r — returning []", jurisdiction)
        return []

    t = (motion_text or "").strip().lower()

    if preprocess := cfg.get("preprocess"):
        preprocessor = _PREPROCESSORS.get(preprocess)
        if preprocessor is None:
            raise ValueError(
                f"classify_motion: unknown preprocessor {preprocess!r} for jurisdiction {jurisdiction!r}"
            )
        t = preprocessor(t)

    if bill_action and (ba_cfg := cfg.get("bill_action")):
        a = bill_action.strip().lower()
        if any(re.search(p, a) for p in ba_cfg.get("committee_passage", [])):
            return ["committee-passage"]

    if any(re.search(p, t) for p in cfg.get("not_passage", [])):
        return []

    if any(re.search(p, t) for p in cfg.get("committee_passage", [])):
        return ["committee-passage"]

    if any(re.search(p, t) for p in cfg.get("passage", [])):
        return ["passage"]

    return ["passage"] if cfg.get("default") == "passage" else []
