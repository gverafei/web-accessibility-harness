"""Deterministic activation and stopping rules for remediation refinement."""


def rag_activation(use_rag, iteration, axe_evidence, lighthouse_evidence):
    """Use measured defects, including the acquired source before iteration one."""
    if not use_rag:
        return False, "disabled"
    if axe_evidence or lighthouse_evidence:
        return True, "measured_failure"
    return False, "no_measured_failure"


def meaningful_improvement(previous_distance, current_distance,
                           previous_retention, current_retention,
                           previous_visual, current_visual, step):
    """Separate useful progress from tiny stochastic ranking changes.

    Automated-target distance remains primary. Once it is unchanged, a
    retention gain of at least half a percentage point is meaningful. Visual
    similarity is only considered for preservation-oriented steps 1--3.
    """
    try:
        distance_gain = float(previous_distance) - float(current_distance)
    except (TypeError, ValueError):
        distance_gain = 0.0
    if distance_gain >= 0.5:
        return True, "automated_target_distance"

    def minimum_retention(values):
        values = values or {}
        measured = []
        for key in ("text_percent", "links_percent", "images_percent", "dynamic_images_percent"):
            try:
                measured.append(float(values.get(key, 100.0)))
            except (TypeError, ValueError):
                measured.append(0.0)
        return min(measured)

    if minimum_retention(current_retention) - minimum_retention(previous_retention) >= 0.5:
        return True, "content_retention"
    if step <= 3:
        try:
            if float(current_visual) - float(previous_visual) >= 1.0:
                return True, "visual_preservation"
        except (TypeError, ValueError):
            pass
    return False, "marginal"
