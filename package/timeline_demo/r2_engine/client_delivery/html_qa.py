#!/usr/bin/env python3
"""Portable offline-HTML layout QA using system Python Playwright + Chrome."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlparse

sys.dont_write_bytecode = True
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from client_delivery.html_static_ledger import (  # noqa: E402
    StaticLedgerError,
    build_expected_static_ledger,
)

EXPECTED_PLAYWRIGHT = "1.59.0"
EXIT_HOLD = 3


class DependencyUnavailable(RuntimeError):
    pass


def launch_failure_reason(exc: Exception) -> str:
    """Return a stable, path-free browser launch classification."""

    detail = str(exc)
    if "kill EPERM" in detail or "SIGABRT" in detail or "Operation not permitted" in detail:
        return "sandbox_process_control_denied"
    if "Executable doesn't exist" in detail or "executable doesn't exist" in detail:
        return "browser_executable_missing"
    if "Target page, context or browser has been closed" in detail:
        return "browser_target_closed"
    return "browser_launch_failed"


def browser_candidates() -> list[tuple[str, Path]]:
    configured = os.environ.get("S2_CHROMIUM_PATH")
    values: list[tuple[str, Path]] = []
    if configured:
        values.append(("configured-chromium", Path(configured).expanduser()))
    values.extend(
        [
            ("google-chrome-macos", Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")),
            ("chromium-macos", Path("/Applications/Chromium.app/Contents/MacOS/Chromium")),
        ]
    )
    for command in ("google-chrome", "chromium", "chromium-browser"):
        resolved = shutil.which(command)
        if resolved:
            values.append((command, Path(resolved)))
    return values


def selected_browser() -> tuple[str, Path]:
    if os.environ.get("S2_HTML_QA_FORCE_UNAVAILABLE") == "1":
        raise DependencyUnavailable("Playwright/Chrome dependency forced unavailable")
    for kind, path in browser_candidates():
        try:
            if path.is_file() and os.access(path, os.X_OK):
                return kind, path.resolve()
        except OSError:
            continue
    raise DependencyUnavailable("Chrome/Chromium executable unavailable")


def dependency_report(*, launch: bool = True) -> dict[str, object]:
    try:
        version = importlib.metadata.version("playwright")
        from playwright.sync_api import sync_playwright
    except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
        raise DependencyUnavailable("Python Playwright dependency unavailable") from exc
    if version != EXPECTED_PLAYWRIGHT:
        raise DependencyUnavailable(
            f"Playwright version mismatch: expected {EXPECTED_PLAYWRIGHT}, got {version}"
        )
    kind, executable = selected_browser()
    browser_version = None
    if launch:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=str(executable))
                try:
                    browser_version = browser.version
                finally:
                    browser.close()
        except Exception as exc:  # Playwright wraps launch errors in its own type.
            raise DependencyUnavailable(
                f"Chrome/Chromium launch check failed:{launch_failure_reason(exc)}"
            ) from exc
    return {
        "status": "pass",
        "engine": "python-playwright-chromium",
        "playwright_version": version,
        "browser_kind": kind,
        "browser_version": browser_version,
        "codex_runtime_required": False,
        "node_runtime_required": False,
    }


def external(url: str) -> bool:
    return urlparse(url).scheme not in {"file", "data", "blob", "about"}


INSPECT_SCRIPT = r"""
async (slides, expectedSlides) => Promise.all(slides.map(async (slide, index) => {
  const sha256 = async (value) => {
    const bytes = new TextEncoder().encode(value);
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    return 'sha256:' + [...new Uint8Array(digest)]
      .map((byte) => byte.toString(16).padStart(2, '0')).join('');
  };
  const staticIdAllowed = (value) => /^(?:watermark:release-state|header:role-label|footer:(?:document-label|source-refs|page-number)|cover-lead|cover-meta-(?:label|value):(?:case_ref|version|materials_as_of|prepared_by|confidentiality)|relationship:(?:parties|chain)-heading|timeline:undated-heading|evidence:(?:matrix|amounts|amount-notes|index)-heading|stage-risk:(?:stages|risks)-heading|next-steps:(?:items|gaps)-heading|scope:(?:boundary|cutoff)|(?:evidence_matrix\.(?:rows|amounts)|stage_risk\.(?:stages|risks)):(?:header|empty))$/.test(value);
  const roleLabels = new Set(['案件概览', '执行摘要', '主体关系', '关键时间线', '要件与证据', '阶段与风险', '缺口与下一步', '范围与说明']);
  const rect = slide.getBoundingClientRect();
  const targetHeight = 720;
  const owners = [...slide.querySelectorAll(
    '[data-semantic-id][data-visible-text-sha256], [data-static-id][data-visible-text-sha256]'
  )];
  const expected = expectedSlides[index] || null;
  const roleClasses = [...slide.classList].filter((value) => value.startsWith('role-'));
  const actualRole = roleClasses.length === 1 ? roleClasses[0].slice(5) : '';
  const actualStaticEntries = owners.map((node, ownerOrdinal) => {
    const staticId = node.getAttribute('data-static-id');
    return staticId ? {
      owner_ordinal: ownerOrdinal,
      id: staticId,
      text: node.textContent || '',
    } : null;
  }).filter(Boolean);
  const roleLocationMatches = Boolean(expected) && actualRole === expected.role;
  const expectedOwnerCountMatches = Boolean(expected)
    && owners.length === expected.owner_count;
  const staticLedgerMatches = Boolean(expected)
    && JSON.stringify(actualStaticEntries) === JSON.stringify(expected.static);
  const releaseWatermarkCount = owners.filter(
    (node) => node.getAttribute('data-static-id') === 'watermark:release-state'
  ).length;
  // An owner-attributed element without the hash attribute would otherwise be
  // excluded from every gate below while the unregistered-text walker still
  // treats its text as owned.  The contract requires the browser side to
  // reject it independently of the static parser.
  const unhashedOwners = [...slide.querySelectorAll(
    '[data-semantic-id]:not([data-visible-text-sha256]), [data-static-id]:not([data-visible-text-sha256])'
  )].map((node) => node.getAttribute('data-semantic-id') || node.getAttribute('data-static-id'));
  const ownerTokens = owners.map((node) => {
    const semanticId = node.getAttribute('data-semantic-id');
    const staticId = node.getAttribute('data-static-id');
    return [semanticId ? 'semantic' : 'static', semanticId || staticId,
      node.getAttribute('data-visible-text-sha256')];
  });
  const ownerHashFailures = [];
  for (const node of owners) {
    const actual = await sha256(node.textContent || '');
    if (actual !== node.getAttribute('data-visible-text-sha256')) {
      ownerHashFailures.push(node.getAttribute('data-semantic-id') || node.getAttribute('data-static-id'));
    }
  }
  const staticIds = owners.map((node) => node.getAttribute('data-static-id')).filter(Boolean);
  const invalidStaticIds = staticIds.filter((value) => !staticIdAllowed(value));
  const duplicateStaticIds = [...new Set(staticIds.filter(
    (value, position) => staticIds.indexOf(value) !== position
  ))];
  const machineEnums = new Set([
    'REVIEW_DRAFT', 'CLIENT_READY',
    'CONFIDENTIAL', 'ATTORNEY_WORK_PRODUCT', 'INTERNAL_REVIEW_ONLY',
  ]);
  const fixedChineseFailures = owners.filter((node) => {
    const staticId = node.getAttribute('data-static-id');
    const value = node.textContent || '';
    // Source/profile semantic text is authoritative and may legitimately
    // contain English identifiers, but an owner whose entire text IS a machine
    // enum is an unmapped fixed label whichever side owns it.
    if (!staticId) return machineEnums.has(value.trim());
    if (staticId === 'watermark:release-state') return value !== '审阅稿';
    if (staticId === 'footer:document-label') return value !== '诉讼可视化';
    if (staticId === 'header:role-label') return !roleLabels.has(value);
    return /LITIGATION\s*BRIEF|CLIENT[\s_-]*DELIVERY|REVIEW[\s_-]*DRAFT|CLIENT[\s_-]*READY|INTERNAL[\s_-]*REVIEW[\s_-]*ONLY|ATTORNEY[\s_-]*WORK[\s_-]*PRODUCT|CONFIDENTIAL/i.test(value);
  });
  const nowrapFailures = owners.filter((node) => {
    const staticId = node.getAttribute('data-static-id') || '';
    if (staticId !== 'watermark:release-state'
        && staticId !== 'header:role-label'
        && staticId !== 'footer:document-label'
        && !staticId.startsWith('cover-meta-label:')) return false;
    const style = getComputedStyle(node);
    return style.whiteSpace !== 'nowrap'
      || node.scrollWidth - node.clientWidth > 0.75
      || node.scrollHeight - node.clientHeight > 0.75;
  });
  const walker = document.createTreeWalker(slide, NodeFilter.SHOW_TEXT);
  const unregisteredVisibleText = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!(node.nodeValue || '').trim()) continue;
    const parent = node.parentElement;
    if (!parent) continue;
    const style = getComputedStyle(parent);
    const range = document.createRange();
    range.selectNodeContents(node);
    const visible = style.display !== 'none' && style.visibility !== 'hidden'
      && Number(style.opacity || 1) > 0 && [...range.getClientRects()]
        .some((item) => item.width > 0.1 && item.height > 0.1);
    if (!visible) continue;
    const owner = parent.closest('[data-semantic-id], [data-static-id]');
    if (!owner || !slide.contains(owner)) {
      unregisteredVisibleText.push((node.nodeValue || '').trim().slice(0, 80));
    }
  }
  const declaredOwnerCount = Number(slide.getAttribute('data-visible-owner-count'));
  const declaredOwnerLedger = slide.getAttribute('data-visible-owner-ledger-sha256');
  const actualOwnerLedger = await sha256(JSON.stringify(ownerTokens));
  const semantic = [...slide.querySelectorAll('[data-semantic-id]')].map((node) => {
    const item = node.getBoundingClientRect();
    return {
      id: node.getAttribute('data-semantic-id'),
      left: item.left, top: item.top, right: item.right, bottom: item.bottom,
    };
  });
  const semanticOverflow = semantic.reduce((maximum, item) => Math.max(
    maximum,
    item.bottom - (rect.top + targetHeight),
    rect.left - item.left,
    item.right - rect.right,
    rect.top - item.top,
  ), 0);
  const articleHorizontalOverflow = Math.max(0, slide.scrollWidth - slide.clientWidth);
  const articleVerticalOverflow = Math.max(0, slide.scrollHeight - slide.clientHeight);
  const overflowPx = Math.max(
    0,
    rect.height - targetHeight,
    articleHorizontalOverflow,
    articleVerticalOverflow,
    semanticOverflow,
  );
  return {
    slide: index + 1,
    width: rect.width,
    height: rect.height,
    clientWidth: slide.clientWidth,
    scrollWidth: slide.scrollWidth,
    clientHeight: slide.clientHeight,
    scrollHeight: slide.scrollHeight,
    semanticCount: semantic.length,
    visibleOwnerCount: owners.length,
    declaredVisibleOwnerCount: declaredOwnerCount,
    visibleOwnerLedgerMatches: declaredOwnerLedger === actualOwnerLedger,
    ownerHashFailureCount: ownerHashFailures.length,
    invalidStaticIdCount: invalidStaticIds.length,
    duplicateStaticIdCount: duplicateStaticIds.length,
    fixedChineseFailureCount: fixedChineseFailures.length,
    nowrapFailureCount: nowrapFailures.length,
    roleLocationMatches,
    expectedOwnerCountMatches,
    staticLedgerMatches,
    releaseWatermarkCount,
    unhashedOwnerCount: unhashedOwners.length,
    unregisteredVisibleTextCount: unregisteredVisibleText.length,
    visibleTextClosureStatus: (
      owners.length === declaredOwnerCount
      && declaredOwnerLedger === actualOwnerLedger
      && ownerHashFailures.length === 0
      && invalidStaticIds.length === 0
      && duplicateStaticIds.length === 0
      && fixedChineseFailures.length === 0
      && nowrapFailures.length === 0
      && roleLocationMatches
      && expectedOwnerCountMatches
      && staticLedgerMatches
      && releaseWatermarkCount === 1
      && unhashedOwners.length === 0
      && unregisteredVisibleText.length === 0
    ) ? 'complete' : 'UNREGISTERED_VISIBLE_TEXT',
    semanticOverflowPx: Math.max(0, semanticOverflow),
    articleHorizontalOverflowPx: articleHorizontalOverflow,
    articleVerticalOverflowPx: articleVerticalOverflow,
    articleOverflowPx: overflowPx,
  };
}))
"""

GLOBAL_VISIBLE_SCRIPT = r"""
() => {
  const allowedPseudoContent = new Set(['none', 'normal', '""', "''"]);
  const pseudoContentFailures = [];
  const elements = [document.documentElement, ...document.querySelectorAll('*')];
  for (const element of elements) {
    for (const pseudo of ['::before', '::after', '::marker']) {
      const value = (getComputedStyle(element, pseudo).content || '').trim();
      if (!allowedPseudoContent.has(value)) {
        pseudoContentFailures.push({
          tag: element.tagName,
          pseudo,
          content: value.slice(0, 80),
        });
      }
    }
  }
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const outsideVisibleText = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!(node.nodeValue || '').trim()) continue;
    const parent = node.parentElement;
    if (!parent || parent.closest('article.slide')) continue;
    const style = getComputedStyle(parent);
    const range = document.createRange();
    range.selectNodeContents(node);
    const visible = style.display !== 'none' && style.visibility !== 'hidden'
      && Number(style.opacity || 1) > 0 && [...range.getClientRects()]
        .some((item) => item.width > 0.1 && item.height > 0.1);
    if (visible) outsideVisibleText.push((node.nodeValue || '').trim().slice(0, 80));
  }
  return {
    pseudoContentFailureCount: pseudoContentFailures.length,
    pseudoContentFailures: pseudoContentFailures.slice(0, 3),
    outsideVisibleTextCount: outsideVisibleText.length,
    outsideVisibleText: outsideVisibleText.slice(0, 3),
  };
}
"""


def inspect_media(
    page, media: str, expected_slides: int, expected_static: list[dict[str, object]]
) -> dict[str, object]:
    page.emulate_media(media=media)
    page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    global_report = page.evaluate(GLOBAL_VISIBLE_SCRIPT)
    if (
        global_report["pseudoContentFailureCount"]
        or global_report["outsideVisibleTextCount"]
    ):
        raise ValueError(
            f"{media}: visible text closure "
            f"{json.dumps(global_report, ensure_ascii=False, sort_keys=True)}"
        )
    report = page.locator("article.slide").evaluate_all(
        INSPECT_SCRIPT, expected_static
    )
    if len(report) != expected_slides:
        raise ValueError(f"{media}: article count {len(report)} != {expected_slides}")
    closure_failures = [
        item for item in report if item["visibleTextClosureStatus"] != "complete"
    ]
    if closure_failures:
        raise ValueError(
            f"{media}: visible text closure "
            f"{json.dumps(closure_failures[:3], ensure_ascii=False, sort_keys=True)}"
        )
    failures = [item for item in report if item["articleOverflowPx"] > 0.75]
    if failures:
        raise ValueError(
            f"{media}: article overflow {json.dumps(failures[:3], ensure_ascii=False, sort_keys=True)}"
        )
    return {
        "media": media,
        "slideCount": len(report),
        "articleOverflowPx": max(item["articleOverflowPx"] for item in report),
        "articleHorizontalOverflowPx": max(
            item["articleHorizontalOverflowPx"] for item in report
        ),
        "articleVerticalOverflowPx": max(
            item["articleVerticalOverflowPx"] for item in report
        ),
        "semanticOverflowPx": max(item["semanticOverflowPx"] for item in report),
        "visibleTextClosureStatus": "complete",
        "visibleOwnerCount": sum(item["visibleOwnerCount"] for item in report),
        "unregisteredVisibleTextCount": 0,
        "ownerHashFailureCount": 0,
        "pseudoContentFailureCount": 0,
        "outsideVisibleTextCount": 0,
        "staticRoleLedgerStatus": "complete",
        "releaseWatermarkStatus": "complete",
        "nowrapStatus": "complete",
        "slides": report,
    }


def inspect_html(
    input_path: Path, expected_slides: int, delivery_ir: dict[str, object]
) -> dict[str, object]:
    if not input_path.is_file() or input_path.is_symlink() or input_path.stat().st_size < 1024:
        raise ValueError("input HTML missing or too small")
    report = dependency_report(launch=False)
    expected_static = build_expected_static_ledger(delivery_ir)
    if len(expected_static) != expected_slides:
        raise ValueError("DeliveryIR/static-ledger slide count mismatch")
    expected_static_sha256 = hashlib.sha256(
        json.dumps(
            expected_static, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    _, executable = selected_browser()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(
                headless=True, executable_path=str(executable)
            )
        except Exception as exc:
            raise DependencyUnavailable(
                f"Chrome/Chromium launch failed:{launch_failure_reason(exc)}"
            ) from exc
        try:
            context = browser.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
            blocked: list[str] = []

            def route_handler(route) -> None:
                if external(route.request.url):
                    blocked.append(route.request.url)
                    route.abort(error_code="blockedbyclient")
                else:
                    route.continue_()

            context.route("**/*", route_handler)
            page = context.new_page()
            page.goto(input_path.resolve().as_uri(), wait_until="load")
            screen = inspect_media(page, "screen", expected_slides, expected_static)
            print_report = inspect_media(page, "print", expected_slides, expected_static)
            pdf = page.pdf(print_background=True, prefer_css_page_size=True)
            print_page_count = len(re.findall(rb"/Type\s*/Page\b", pdf))
            if print_page_count != expected_slides:
                raise ValueError(
                    f"print page count {print_page_count} != {expected_slides}"
                )
            if blocked:
                raise ValueError("external requests blocked")
            context.close()
            return {
                **report,
                "status": "pass",
                "engine": "python-playwright-chromium",
                "browserVersion": browser.version,
                "networkRequests": 0,
                "expectedSlides": expected_slides,
                "expectedStaticLedgerSha256": "sha256:" + expected_static_sha256,
                "printPageCount": print_page_count,
                "screen": screen,
                "print": print_report,
            }
        finally:
            browser.close()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--input")
    parser.add_argument("--expected-slides", type=int)
    parser.add_argument("--delivery-ir-stdin", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.doctor:
            print(json.dumps(dependency_report(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            not args.input
            or not args.expected_slides
            or args.expected_slides < 1
            or not args.delivery_ir_stdin
        ):
            raise ValueError(
                "--input, positive --expected-slides and --delivery-ir-stdin are required"
            )
        try:
            delivery_ir = json.loads(sys.stdin.read())
        except json.JSONDecodeError as exc:
            raise ValueError("DeliveryIR stdin is not JSON") from exc
        if not isinstance(delivery_ir, dict):
            raise ValueError("DeliveryIR stdin must be an object")
        print(
            json.dumps(
                inspect_html(Path(args.input), args.expected_slides, delivery_ir),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except DependencyUnavailable as exc:
        print(f"HOLD-HTML-DEPENDENCY:{exc}", file=sys.stderr)
        return EXIT_HOLD
    except (OSError, ValueError) as exc:
        print(f"HTML-QA-FAILED:{type(exc).__name__}:{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"HTML-QA-FAILED:{type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
