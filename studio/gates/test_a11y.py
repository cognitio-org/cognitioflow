import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from a11y import check_accessibility


class FakeProbe:
    def __init__(
        self,
        focus=True,
        motion=True,
        tap_target=44.0,
        contrast=7.0,
        raises=None,
    ):
        self.focus = focus
        self.motion = motion
        self.tap_target = tap_target
        self.contrast = contrast
        self.raises = raises

    def _raise_if_requested(self, method):
        if self.raises == method:
            raise RuntimeError("broken probe")

    def focus_visible(self):
        self._raise_if_requested("focus_visible")
        return self.focus

    def reduced_motion_respected(self):
        self._raise_if_requested("reduced_motion_respected")
        return self.motion

    def min_tap_target_px(self):
        self._raise_if_requested("min_tap_target_px")
        return self.tap_target

    def min_contrast_ratio(self):
        self._raise_if_requested("min_contrast_ratio")
        return self.contrast


if __name__ == "__main__":
    compliant = check_accessibility(FakeProbe())
    assert compliant.ok is True
    assert compliant.issues == []

    focus_failure = check_accessibility(FakeProbe(focus=False))
    assert focus_failure.ok is False
    assert focus_failure.issues == ["no visible keyboard focus"]

    motion_failure = check_accessibility(FakeProbe(motion=False))
    assert motion_failure.ok is False
    assert motion_failure.issues == ["ignores prefers-reduced-motion"]

    tap_failure = check_accessibility(FakeProbe(tap_target=31.0))
    assert tap_failure.ok is False
    assert tap_failure.issues == ["tap target 31.0px < 32.0px"]

    contrast_failure = check_accessibility(FakeProbe(contrast=4.0))
    assert contrast_failure.ok is False
    assert contrast_failure.issues == ["contrast 4.0 < 4.5"]

    probe_failure = check_accessibility(FakeProbe(raises="focus_visible"))
    assert probe_failure.ok is False
    assert probe_failure.issues == ["probe failure: broken probe"]

    print("OK")
