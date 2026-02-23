"""
Image analyzer: missing alt text, broken images, large file sizes, lazy loading.
"""
from __future__ import annotations

from models import AuditConfig, Issue, PageData
from analyzers.base import BaseAnalyzer
from config import LARGE_IMAGE_SIZE_BYTES


class ImageAnalyzer(BaseAnalyzer):
    category = "Images"

    def analyze(
        self,
        page: PageData,
        all_pages: dict[str, PageData],
        config: AuditConfig,
    ) -> list[Issue]:
        if not page.is_html or page.status_code not in range(200, 300):
            return []

        issues: list[Issue] = []
        url = page.url

        has_any_lazy = any(img.loading == "lazy" for img in page.images)
        above_fold_threshold = 3  # first N images assumed above fold

        for idx, img in enumerate(page.images):
            # ── Broken image ──────────────────────────────────────────────────
            if img.is_broken:
                issues.append(self.critical(
                    url, "broken_image",
                    "Image is broken (returns 4xx/5xx or failed to load).",
                    "Fix the broken image URL or remove the <img> tag.",
                    detail=img.src,
                    element="<img>",
                ))
                continue

            # ── Missing alt text ──────────────────────────────────────────────
            # alt="" is valid for decorative images; missing alt attribute is the problem
            if img.alt == "" and not _is_likely_decorative(img):
                issues.append(self.warning(
                    url, "missing_alt_text",
                    "Image is missing alt text. This hurts accessibility and image SEO.",
                    "Add descriptive alt text that conveys the image's content and function.",
                    detail=img.src,
                    element="<img>",
                ))

            # ── Large image ───────────────────────────────────────────────────
            if img.size_bytes > LARGE_IMAGE_SIZE_BYTES:
                size_kb = img.size_bytes // 1024
                issues.append(self.warning(
                    url, "large_image",
                    f"Image is {size_kb} KB — larger than the recommended {LARGE_IMAGE_SIZE_BYTES // 1024} KB.",
                    "Compress and optimize this image, or use modern formats (WebP, AVIF).",
                    detail=f"{img.src} ({size_kb} KB)",
                    element="<img>",
                ))

            # ── Missing lazy loading ──────────────────────────────────────────
            if idx >= above_fold_threshold and img.loading != "lazy" and len(page.images) > above_fold_threshold:
                issues.append(self.info(
                    url, "missing_lazy_load",
                    "Below-fold image is not using lazy loading.",
                    'Add loading="lazy" to images that are not visible on initial page load.',
                    detail=img.src,
                    element="<img>",
                ))

        # ── No lazy loading at all on image-heavy pages ───────────────────────
        if len(page.images) > 3 and not has_any_lazy:
            issues.append(self.info(
                url, "no_lazy_loading",
                f"Page has {len(page.images)} images but none use lazy loading.",
                'Add loading="lazy" to below-fold images to improve initial page load performance.',
            ))

        return issues


def _is_likely_decorative(img) -> bool:
    """
    Heuristic: image is likely decorative if it has no detectable content signals.
    We use empty alt="" as valid for these.
    """
    # If alt attribute is explicitly set (even to ""), we treat as intentional
    # The issue is only when alt is truly absent (parsed as empty string from missing attribute)
    # Since BeautifulSoup returns "" for missing attrs, we just check size heuristics
    try:
        w = int(img.width or 0)
        h = int(img.height or 0)
        if 0 < w <= 5 and 0 < h <= 5:
            return True   # 1×1 or tiny tracking pixel
    except (ValueError, TypeError):
        pass
    return False
