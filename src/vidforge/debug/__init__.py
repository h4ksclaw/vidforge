"""VidForge debug infrastructure — report building and file upload.

Every debug script should use ReportBuilder (or subclass DebugScript) to produce
a single HTML report uploaded to s.h4ks.com. That is the canonical debug output.

Pattern:

    class MyDebug(DebugScript):
        def run(self, **kwargs) -> None:
            report = self.report("My Debug Title", "what this tests")
            section = report.add_section("Some result")
            section.add_stat("key", "value")
            # report auto-uploads to s.h4ks.com

    MyDebug().run(limit=10)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from vidforge.debug.report import ReportBuilder
from vidforge.debug.upload import upload_file

__all__ = ["DebugScript", "ReportBuilder", "upload_file"]


class DebugScript:
    """Base class for debug scripts.

    Enforces the pattern: build a ReportBuilder, populate it, upload to s.h4ks.com.
    Subclass and implement run(). The report is auto-uploaded when run() returns.
    """

    def report(self, title: str, description: str = "") -> ReportBuilder:
        """Create a new report for this debug session."""
        self._report = ReportBuilder(title, description)
        return self._report

    def upload_asset(self, path: str | Path) -> str | None:
        """Upload a local file to s.h4ks.com and return the URL."""
        return upload_file(path)

    def run(self, **kwargs: Any) -> str | None:
        """Implement in subclasses. Build self.report(), populate sections, return URL."""
        raise NotImplementedError

    def __call__(self, **kwargs: Any) -> str | None:
        """Run the debug script and return the report URL (or None on failure)."""
        url = self.run(**kwargs)
        if url:
            print(f"Report: {url}")
        else:
            print("Report: upload failed (saved locally)", file=sys.stderr)
        return url
