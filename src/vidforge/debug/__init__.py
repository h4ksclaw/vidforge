"""VidForge debug infrastructure — report building and file upload.

Heights-specific debug scripts have moved to vidforge.generators.heights.debug.
This package re-exports the shared utilities.
"""

from vidforge.debug.report import ReportBuilder
from vidforge.debug.upload import upload_file

__all__ = ["ReportBuilder", "upload_file"]
