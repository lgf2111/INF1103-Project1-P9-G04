"""Map a calculated response score to its priority label."""


class PriorityRouter:
    """Apply the shared response-priority thresholds."""

    def priority_for(self, score):
        """Return HIGH, MEDIUM, or LOW for a calculated score."""
        if score >= 70:
            return "HIGH"
        if score >= 35:
            return "MEDIUM"
        return "LOW"
