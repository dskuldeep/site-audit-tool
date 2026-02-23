"""
Base class for all page analyzers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from models import AuditConfig, Issue, PageData, Severity


class BaseAnalyzer(ABC):
    """All analyzers inherit from this class."""

    category: str = "Uncategorized"

    @abstractmethod
    def analyze(
        self,
        page: PageData,
        all_pages: dict[str, PageData],
        config: AuditConfig,
    ) -> list[Issue]:
        """Analyze a single page and return a list of issues."""
        ...

    # ── Convenience factory ───────────────────────────────────────────────────

    def _issue(
        self,
        url: str,
        issue_type: str,
        severity: str,
        description: str,
        recommendation: str,
        detail: str = "",
        affected_element: str = "",
    ) -> Issue:
        return Issue(
            url=url,
            category=self.category,
            issue_type=issue_type,
            severity=severity,
            description=description,
            recommendation=recommendation,
            detail=detail,
            affected_element=affected_element,
        )

    def critical(self, url, issue_type, description, recommendation, detail="", element="") -> Issue:
        return self._issue(url, issue_type, Severity.CRITICAL, description, recommendation, detail, element)

    def warning(self, url, issue_type, description, recommendation, detail="", element="") -> Issue:
        return self._issue(url, issue_type, Severity.WARNING, description, recommendation, detail, element)

    def info(self, url, issue_type, description, recommendation, detail="", element="") -> Issue:
        return self._issue(url, issue_type, Severity.INFO, description, recommendation, detail, element)
