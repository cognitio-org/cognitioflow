from dataclasses import dataclass
from typing import Protocol


class A11yProbe(Protocol):
    def focus_visible(self) -> bool: ...
    def reduced_motion_respected(self) -> bool: ...
    def min_tap_target_px(self) -> float: ...
    def min_contrast_ratio(self) -> float: ...


@dataclass
class A11yVerdict:
    ok: bool
    issues: list[str]


def check_accessibility(
    probe: A11yProbe,
    min_tap_px: float = 32.0,
    min_contrast: float = 4.5,
) -> A11yVerdict:
    issues = []

    try:
        if not probe.focus_visible():
            issues.append("no visible keyboard focus")
    except Exception as e:
        issues.append(f"probe failure: {e}")

    try:
        if not probe.reduced_motion_respected():
            issues.append("ignores prefers-reduced-motion")
    except Exception as e:
        issues.append(f"probe failure: {e}")

    try:
        tap_target = probe.min_tap_target_px()
        if tap_target < min_tap_px:
            issues.append(f"tap target {tap_target}px < {min_tap_px}px")
    except Exception as e:
        issues.append(f"probe failure: {e}")

    try:
        contrast = probe.min_contrast_ratio()
        if contrast < min_contrast:
            issues.append(f"contrast {contrast} < {min_contrast}")
    except Exception as e:
        issues.append(f"probe failure: {e}")

    return A11yVerdict(ok=not issues, issues=issues)
