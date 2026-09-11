"""Backwards-compatibility re-exports for the synth dialogs.

Both classes have been moved to their own modules. Import from there for
new code; this shim keeps existing imports working without changes.
"""

from pyp6.ui.dialogs.synth_dialog import SynthDialog
from pyp6.ui.dialogs.waveform_creator import WaveformCreatorDialog

__all__ = ["SynthDialog", "WaveformCreatorDialog"]
