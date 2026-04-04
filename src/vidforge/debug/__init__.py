"""Debug tools for vidforge — live integration testing with visual reports.

Run actual pipeline code, collect results, generate a sharable HTML preview.
No mocks. Real APIs, real image processing, real uploads.
"""

from vidforge.debug.report import ReportBuilder
from vidforge.debug.upload import upload_file

__all__ = ["ReportBuilder", "upload_file"]
