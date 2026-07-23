"""WCAG contrast checker for KernelWorx brand colors.

Run from repo root:
    python3 scripts/contrast_check.py
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Color:
    name: str
    hex: str

    @property
    def rgb(self) -> tuple[float, float, float]:
        h = self.lstrip_hash(self.hex)
        return (
            int(h[0:2], 16) / 255.0,
            int(h[2:4], 16) / 255.0,
            int(h[4:6], 16) / 255.0,
        )

    @staticmethod
    def lstrip_hash(value: str) -> str:
        return value.lstrip("#")

    @property
    def luminance(self) -> float:
        r, g, b = self.rgb
        # sRGB to linear
        def linear(c: float) -> float:
            return c / 12.92 if c <= 0.03928 else math.pow((c + 0.055) / 1.055, 2.4)

        return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)

    def contrast_against(self, other: "Color") -> float:
        l1, l2 = self.luminance, other.luminance
        lighter = max(l1, l2)
        darker = min(l1, l2)
        return (lighter + 0.05) / (darker + 0.05)


# Brand palette (from frontend/src/lib/theme.ts)
COLORS = [
    Color("white", "#ffffff"),
    Color("black", "#1a1a1a"),
    Color("primary-1", "#ebf8ff"),
    Color("primary-2", "#c2e9ff"),
    Color("primary-3", "#94d0f7"),
    Color("primary-5", "#3e94de"),
    Color("primary-6", "#1976d2"),
    Color("primary-7", "#0c57ab"),
    Color("primary-link", "#005a9c"),
    Color("primary-9", "#00265e"),
    Color("success-main", "#388e3c"),
    Color("success-bg", "#c4cfc2"),
    Color("success-border", "#9fb59e"),
    Color("success-hover", "#569c56"),
    Color("success-active", "#15431c"),
    Color("warning-main", "#f57c00"),
    Color("warning-bg", "#fff7e6"),
    Color("warning-border", "#ffcb7a"),
    Color("warning-hover", "#ff9c29"),
    Color("warning-active", "#8a4200"),
    Color("error-main", "#dc004e"),
    Color("error-bg", "#ffe6ea"),
    Color("error-border", "#ff7a9c"),
    Color("error-hover", "#e82564"),
    Color("error-active", "#b50046"),
    Color("error-text", "#9e0036"),
    Color("text-primary", "#4b4b4b"),
    Color("text-secondary", "#595959"),
    Color("text-tertiary", "#595959"),
    Color("text-quaternary", "#757575"),
    Color("fill-main", "#e0e0e0"),
    Color("fill-secondary", "#f3f3f3"),
    Color("fill-tertiary", "#f7f7f7"),
    Color("fill-quaternary", "#fbfbfb"),
    Color("bg-layout", "#f7f7f7"),
    Color("bg-container", "#ffffff"),
    Color("bg-paper", "#ffffff"),
    Color("info-light", "#c2e9ff"),
    Color("DevFooter-bg", "#4d4d4d"),  # rgba(0,0,0,0.7) over white
    Color("DevFooter-text", "#ffffff"),  # opaque white over DevFooter-bg
    Color("border-main", "#e0e0e0"),
    Color("border-secondary", "#f3f3f3"),
    Color("grey-50", "#fbfbfb"),
    Color("grey-100", "#f7f7f7"),
    Color("grey-200", "#f3f3f3"),
    Color("grey-300", "#e0e0e0"),
    Color("grey-400", "#cccccc"),
    Color("grey-500", "#a3a3a3"),
    Color("grey-600", "#7a7a7a"),
    Color("grey-700", "#4b4b4b"),
    Color("grey-800", "#333333"),
    Color("grey-900", "#1a1a1a"),
]

TEXT_USES = [
    # (text_color, background_color, size_description, location)
    ("text-primary", "bg-container", "normal", "default body text on white cards/pages"),
    ("text-primary", "bg-layout", "normal", "body text on layout background"),
    ("text-secondary", "bg-container", "normal", "body2, subtitle on white"),
    ("text-secondary", "bg-layout", "normal", "body2, subtitle on grey layout"),
    ("text-secondary", "grey-50", "normal", "Mid-page CTA box on grey.50"),
    ("text-secondary", "grey-100", "normal", "DeviceFrame URL, catalog headers, table headers"),
    ("text-secondary", "info-light", "normal", "info callouts on CreateCampaignPage"),
    ("text-secondary", "warning-bg", "normal", "warning callouts"),
    ("text-tertiary", "bg-container", "normal", "caption, helper text on white"),
    ("text-tertiary", "bg-layout", "normal", "caption on grey layout"),
    ("text-tertiary", "bg-paper", "normal", "LandingFooter footer text"),
    ("text-tertiary", "fill-main", "normal", "disabled buttons"),
    ("text-quaternary", "bg-container", "normal", "input placeholders on white"),
    ("white", "primary-9", "normal", "stats band stat values over primary"),
    ("white", "primary-9", "normal", "stats band labels over primary"),
    ("white", "primary-9", "large", "final CTA heading over primary"),
    ("white", "primary-9", "normal", "final CTA body over primary"),
    ("white", "primary-9", "large", "final CTA sponsor button text"),
    ("white", "primary-9", "normal", "final CTA caption"),
    ("primary-link", "white", "normal", "outlined buttons, text buttons, links"),
    ("primary-link", "bg-container", "normal", "links on white"),
    ("primary-link", "white", "normal", "link hover state"),
    ("primary-9", "white", "normal", "link active state"),
    ("error-text", "error-bg", "normal", "error alerts"),
    ("success-active", "success-bg", "normal", "success alerts"),
    ("primary-9", "primary-1", "normal", "info alerts"),
    ("warning-active", "warning-bg", "normal", "warning alerts"),
    ("primary-6", "white", "large", "containedPrimary button text"),
    ("white", "error-main", "large", "containedSecondary (error) button text"),
    ("primary-6", "bg-container", "large", "outlinedPrimary button text"),
    ("error-main", "bg-container", "large", "outlinedSecondary button text"),
    ("text-secondary", "bg-container", "normal", "icon button default"),
    ("primary-6", "white", "normal", "FAQ accordion expand icon"),
    ("text-secondary", "bg-container", "normal", "SVG illustration placeholders"),
    ("white", "primary-9", "normal", "sidebar selected nav item"),
    ("white", "primary-7", "normal", "sidebar selected nav item hover"),
    ("error-text", "error-bg", "normal", "sidebar selected admin nav item"),
    ("error-text", "error-bg", "normal", "sidebar admin nav item hover"),
    ("error-text", "bg-container", "normal", "sidebar admin nav item default"),
    ("primary-link", "white", "normal", "Dialog titles (Edit/Create Scout)"),
    ("text-secondary", "bg-paper", "normal", "LandingHeader nav links"),
    ("DevFooter-text", "DevFooter-bg", "normal", "DevFooter over page (assumes white behind)"),
]


def rgba_to_rgb(rgba_hex_or_name: str, background: Color | None = None) -> Color:
    """Convert rgba() description to an effective RGB color over a background."""
    rgba_hex_or_name = rgba_hex_or_name.strip()
    if rgba_hex_or_name.startswith("rgba("):
        inner = rgba_hex_or_name[5:-1]
        parts = [p.strip() for p in inner.split(",")]
        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
        a = float(parts[3])
        bg = background or Color("white", "#ffffff")
        br, bg_, bb = (int(c * 255) for c in bg.rgb)

        def blend(fg: int, back: int) -> int:
            return round(a * fg + (1 - a) * back)

        blended = Color(
            rgba_hex_or_name,
            f"#{blend(r, br):02x}{blend(g, bg_):02x}{blend(b, bb):02x}",
        )
        return blended
    return next(c for c in COLORS if c.name == rgba_hex_or_name)


def main() -> int:
    print("WCAG AAA contrast audit")
    print("=" * 80)

    print("Text/background combinations used in the app:")
    print(f"{'Location':<45} {'Ratio':>8} {'AAA':>6} {'AA':>6}")
    print("-" * 80)

    for fg_name, bg_name, size, location in TEXT_USES:
        bg_color = next(c for c in COLORS if c.name == bg_name)
        fg_color = rgba_to_rgb(fg_name, bg_color)
        ratio = fg_color.contrast_against(bg_color)
        threshold_aaa = 4.5 if size == "large" else 7.0
        threshold_aa = 3.0 if size == "large" else 4.5
        aaa_ok = "PASS" if ratio >= threshold_aaa else "FAIL"
        aa_ok = "PASS" if ratio >= threshold_aa else "FAIL"
        print(f"{location:<45} {ratio:>7.2f}:1 {aaa_ok:>6} {aa_ok:>6}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
