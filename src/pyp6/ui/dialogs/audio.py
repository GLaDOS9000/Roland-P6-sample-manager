"""Backwards-compatibility re-exports for the audio dialogs.

Both classes have been moved to their own modules. Import from there for
new code; this shim keeps existing imports working without changes.
"""

from pyp6.ui.dialogs.audio_preview import AudioPreviewDialog
from pyp6.ui.dialogs.chop import ChopDialog

__all__ = ["AudioPreviewDialog", "ChopDialog"]
