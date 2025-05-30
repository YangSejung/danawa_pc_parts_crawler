from __future__ import annotations

"""Nanoreview Benchmark Crawler (class‑based)
================================================

Crawls CPU / GPU benchmark scores from **nanoreview.net** and saves them
into per‑category CSV files.

Key features
------------
* Cloudflare‑bypassing HTTP client (`cloudscraper`) with retry &
  exponential back‑off.
* Class design (`NanoreviewBenchmarkCrawler`) so it can be instantiated
  and integrated like other project crawlers.
* Category behaviour (CPU / GPU) parametrised via `CategoryConfig`
  dataclass – easy to add more categories later.
* Multi‑process support (`multiprocessing.Pool`) out of the box – the
  default worker count is half the available CPU cores.
* Clear logging (`logging` module) and full type‑hints for readability
  and static analysis.

This file is **self‑contained**: no parts omitted.
"""

###############################################################################
# Imports                                                                     #
###############################################################################

import csv
import logging
import random
import time
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import certifi
import cloudscraper
from bs4 import BeautifulSoup
from requests.exceptions import RequestException

###############################################################################
# Paths & logging                                                             #
###############################################################################

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

_logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

###############################################################################
# Constants                                                                   #
###############################################################################

BAR_SELECTOR = ".score-bar"
NAME_SELECTOR = ".score-bar-name"
VALUE_SELECTOR = ".score-bar-result-number"
FPS_TABLE_CAPTION = "Average FPS by Resolution"
FPS_ROW_SEL = "table.specs-table tbody tr"
FPS_RESOLUTION_SEL = "td.cell-h"
FPS_VALUE_SEL = "td.cell-s"

###############################################################################
# Data models                                                                 #
###############################################################################

@dataclass(frozen=True, slots=True)
class CategoryConfig:
    """Static configuration for a benchmark category (CPU / GPU)."""

    name: str  # Human‑readable label (CPU, GPU …)
    url: str  # Listing page URL
    metric_cards: Sequence[str]  # H3 Titles of desired metric cards
    csv_columns: Sequence[str]  # Header row for the output file
    out_subdir: str  # Sub‑folder of RAW_DIR

###############################################################################
# Fixed config instances                                                      #
###############################################################################

CPU_CONFIG = CategoryConfig(
    name="CPU",
    url="https://nanoreview.net/en/cpu-list/desktop-chips-rating",
    metric_cards=("Cinebench", "GeekBench v6", "Blender"),
    csv_columns=(
        "Category",
        "name",
        "Cinebench R23 (Single-Core)",
        "Cinebench R23 (Multi-Core)",
        "Geekbench 6 (Single-Core)",
        "Geekbench 6 (Multi-Core)",
        "Blender CPU",
    ),
    out_subdir="CPU",
)

GPU_CONFIG = CategoryConfig(
    name="GPU",
    url="https://nanoreview.net/en/gpu-list/desktop-graphics-rating",
    metric_cards=("3D Mark", "GeekBench 6 OpenCL", "Blender"),
    csv_columns=(
        "Category",
        "name",
        "Steel Nomad Lite Score",
        "GB6 Compute Score",
        "Blender GPU",
        "Average FPS by 1080p High",
        "Average FPS by 1080p Ultra",
        "Average FPS by 1440p Ultra",
        "Average FPS by 4K Ultra",
    ),
    out_subdir="VGA",
)

DEFAULT_CATEGORIES: tuple[CategoryConfig, ...] = (CPU_CONFIG, GPU_CONFIG)

###############################################################################
# Utility functions (module‑private)                                          #
###############################################################################

def _retry(max_tries: int = 3, backoff: float = 1.5):  # noqa: D401 – decorator
    """Small exponential‑back‑off retry decorator for transient HTTP errors."""

    def decorator(fn):  # type: ignore[ban-types]
        def wrapped(*args, **kwargs):  # noqa: ANN001 – dynamic
            delay = 1.0
            for attempt in range(1, max_tries + 1):
                try:
                    return fn(*args, **kwargs)
                except RequestException as exc:
                    if attempt == max_tries:
                        raise
                    _logger.warning("%s failed (%s) – retrying in %.1fs", fn.__name__, exc, delay)
                    time.sleep(delay)
                    delay *= backoff
        return wrapped

    return decorator

###############################################################################
# Main crawler class                                                          #
###############################################################################

class NanoreviewBenchmarkCrawler:
    """Benchmark crawler encapsulating all logic inside a class."""

    def __init__(self, categories: Iterable[CategoryConfig] | None = None):
        self.categories: tuple[CategoryConfig, ...] = tuple(categories) if categories else DEFAULT_CATEGORIES
        _logger.debug("Categories initialised: %s", ", ".join(c.name for c in self.categories))

    # ───────────────────────────── HTTP helpers ────────────────────────────
    @staticmethod
    def _create_scraper() -> cloudscraper.CloudScraper:
        scraper = cloudscraper.create_scraper()
        scraper.verify = certifi.where()
        return scraper

    @_retry()
    def _get_html(self, scraper: cloudscraper.CloudScraper, url: str) -> str:
        return scraper.get(url, timeout=30).text

    # ───────────────────────────── Parsing helpers ─────────────────────────
    def _fetch_listing(self, scraper: cloudscraper.CloudScraper, url: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(self._get_html(scraper, url), "html.parser")
        table = soup.find("table", class_="table-list")
        if not table:
            _logger.warning("Listing table not found: %s", url)
            return []
        items: list[tuple[str, str]] = []
        for row in table.select("tbody tr"):
            anchor = row.find("a")
            if anchor and anchor.get("href"):
                name = anchor.get_text(strip=True)
                href = anchor["href"].lstrip("/")
                items.append((name, f"https://nanoreview.net/{href}"))
        return items

    @staticmethod
    def _parse_metric_card(card_node) -> list[tuple[str, str]]:  # type: ignore[valid-type]
        results: list[tuple[str, str]] = []
        for bar in card_node.select(BAR_SELECTOR):
            metric = bar.select_one(NAME_SELECTOR).get_text(strip=True)
            score = bar.select_one(VALUE_SELECTOR).get_text(strip=True)
            results.append((metric, score))
        return results

    def _parse_metrics(self, html: str, card_titles: Iterable[str]) -> dict[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        metrics: dict[str, str] = {}
        for title in card_titles:
            header = soup.find("h3", class_="title-h2", string=title)
            if not header:
                continue
            card = header.find_parent("div", class_="card")
            for metric, score in self._parse_metric_card(card):
                metrics[metric] = score
        return metrics

    def _parse_fps_table(self, html: str) -> Mapping[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        caption = soup.find("caption", class_="title-h3", string=FPS_TABLE_CAPTION)
        if not caption:
            return {}
        table = caption.find_parent("table", class_="specs-table")
        fps: dict[str, str] = {}
        for row in table.select(FPS_ROW_SEL):
            res = row.select_one(FPS_RESOLUTION_SEL).get_text(strip=True)
            val = row.select_one(FPS_VALUE_SEL).get_text(strip=True)
            fps[res] = val
        return fps

    # ───────────────────────────── Category crawl ──────────────────────────
    def _crawl_one_category(self, cfg: CategoryConfig) -> None:
        scraper = self._create_scraper()
        _logger.info("[%s] Listing scrape …", cfg.name)
        listing = self._fetch_listing(scraper, cfg.url)
        _logger.info("[%s] %d items found", cfg.name, len(listing))

        total = len(listing)
        step = max(1, total // 20)
        rows: list[list[str]] = []
        start = time.perf_counter()

        for idx, (comp_name, detail_url) in enumerate(listing, 1):
            time.sleep(random.uniform(1.0, 2.0))  # polite delay
            try:
                html = self._get_html(scraper, detail_url)
                metrics = self._parse_metrics(html, cfg.metric_cards)

                # GPU: merge FPS metrics
                if cfg.name == "GPU":
                    for res, value in self._parse_fps_table(html).items():
                        metrics[f"Average FPS by {res}"] = value

                row = [cfg.name, comp_name] + [metrics.get(col, "") for col in cfg.csv_columns[2:]]
                rows.append(row)
                # _logger.debug("%s scraped", comp_name)
            except Exception as exc:  # pylint: disable=broad-except
                _logger.error("[%s] %s failed: %s", cfg.name, comp_name, exc, exc_info=True)

            # -------- 진행상황 로그 -------------
            if idx % step == 0 or idx == total:
                pct = idx / total * 100  # 0-100 %
                elapsed = time.perf_counter() - start
                _logger.info("[%s] %.1f %% (%d/%d) – %.0f s 경과",cfg.name, pct, idx, total, elapsed)

        out_dir = RAW_DIR / cfg.out_subdir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{cfg.name}_benchmark.csv"
        self._write_csv(out_path, cfg.csv_columns, rows)
        _logger.info("[%s] Written %d records → %s", cfg.name, len(rows), out_path)

    # ───────────────────────────── CSV helper ──────────────────────────────
    @staticmethod
    def _write_csv(path: Path, headers: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
        with path.open("w", newline="", encoding="utf8") as fp:
            writer = csv.writer(fp)
            writer.writerow(headers)
            writer.writerows(rows)

    # ───────────────────────────── Public API ──────────────────────────────
    def crawl(self, processes: int | None = None) -> None:
        """Crawl all configured categories using a process pool."""
        worker_count = processes if processes is not None else max(cpu_count() // 2, 1)
        _logger.info("Starting crawl with %d worker(s)…", worker_count)
        t0 = time.perf_counter()

        with Pool(worker_count) as pool:
            pool.map(self._crawl_one_category, self.categories)

        _logger.info("elapsed %.1f s – all categories done",time.perf_counter() - t0)

###############################################################################
# Script entry‑point                                                          #
###############################################################################

if __name__ == "__main__":
    NanoreviewBenchmarkCrawler().crawl(processes=2)
