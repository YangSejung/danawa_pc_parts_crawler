# -*- coding: utf-8 -*-

import csv
import time
import traceback
import logging
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Iterable, List, Tuple

from selenium.webdriver import Chrome, ChromeOptions
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from selenium.common.exceptions import (
    StaleElementReferenceException,
    NoSuchElementException,
    TimeoutException,
    ElementClickInterceptedException,
)

# -------- 로깅 설정 ---------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
_stream = logging.StreamHandler()
_stream.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.addHandler(_stream)

# -------------- 상수 ------------------
BASE_DIR = Path(__file__).resolve().parent.parent
# DRIVER_PATH = BASE_DIR / "driver" / "chromedriver.exe"
DRIVER_PATH = BASE_DIR / "driver" / "chromedriver"

CATEGORY_URLS  = {
    "CPU": "https://prod.danawa.com/list/?cate=112747",
    "쿨러/튜닝": "https://prod.danawa.com/list/?cate=11236855",
    "메인보드": "https://prod.danawa.com/list/?cate=112751",
    "RAM": "https://prod.danawa.com/list/?cate=112752",
    "그래픽카드(VGA)": "https://prod.danawa.com/list/?cate=112753",
    "SSD": "https://prod.danawa.com/list/?cate=112760",
    "HDD": "https://prod.danawa.com/list/?cate=112763",
    "케이스": "https://prod.danawa.com/list/?cate=112775",
    "파워": "https://prod.danawa.com/list/?cate=112777",
}

CATEGORIES: list[tuple[str, str]] = [
    ("CPU", "CPU"),
    # ("쿨러/튜닝", "Cooler"),
    # ("메인보드", "Motherboard"),
    # ("RAM", "Memory"),
    # ("그래픽카드(VGA)", "VGA"),
    # ("SSD", "SSD"),
    # ("HDD", "HDD"),
    # ("케이스", "Case"),
    # ("파워", "PSU"),
]

# 체크 박스
CHECKBOX_OPTIONS: dict[str, list[str]] = {
    "CPU": [
        "DDR5",
        "DDR5, DDR4",
        "DDR4",
        "정품",
        "멀티팩(정품)",
        "밸류팩(정품)",
        "벌크(정품)",
        "인텔(소켓1851)",
        "인텔(소켓1700)",
        "인텔(소켓1200)",
        "인텔(소켓1151v2)",
        "인텔(소켓1151)",
        "인텔(소켓1150)",
        "AMD(소켓AM5)",
        "AMD(소켓AM4)"
    ],
    "쿨러/튜닝": ["CPU 쿨러","LGA1851", "LGA1700", "LGA1200", "LGA115x","AM5", "AM4"],
    "메인보드": [
        "인텔 CPU용",
        "AMD CPU용",
        "AMD(소켓AM5)",
        "AMD(소켓AM4)",
        "DDR5",
        "DDR4",
        "인텔(소켓1851)",
        "인텔(소켓1700)",
        "인텔(소켓1200)",
        "인텔(소켓1151v2)",
        "인텔(소켓1151)",
        "인텔(소켓1150)",
    ],
    "RAM": ["데스크탑용", "DDR5", "DDR4"],
    "그래픽카드(VGA)": [],
    "SSD": [
        "TLC",
        "QLC",
        "PCIe5.0x4 (128GT/s)",
        "PCIe4.0x4 (64GT/s)",
        "PCIe3.0x4 (32GT/s)",
        "SATA3 (6Gb/s)",
        "M.2 (2280)",
        "6.4cm(2.5형)",
        "M.2 (2242)"
    ],
    "HDD": ["HDD (PC용)", "8.9cm(3.5인치)", "SATA3 (6Gb/s)", "CMR(PMR)", "SMR(PMR)"],
    "케이스": ["ATX 케이스", "M-ATX 케이스", "미니ITX", "튜닝 케이스"],
    "파워": ["ATX 파워", "M-ATX(SFX) 파워", "TFX 파워"],
}

# --------- 데이터 모델 --------------------
@dataclass(slots=True)
class PriceEntry:
    pid: str
    price: int | None

    def as_row(self) -> list[str | int]:
        return [self.pid, self.price if self.price is not None else ""]

# ------------- 크롤러 --------------------

class PriceCrawler:
    def __init__(self):
        options = ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument('--start-maximized')  # 최대화 모드로 시작
        options.add_argument("lang=ko_KR")

        self.driver = Chrome(service = Service(str(DRIVER_PATH)), options=options)
        self.wait = WebDriverWait(self.driver, 10)

    # --------- public API -------------
    def crawl(self, cat_name: str, cat_code: str) -> None:
        try:
            url = CATEGORY_URLS[cat_name]
            logger.info(f"[{cat_name}] 시작")
            self.driver.get(url)

            self._click_checkboxes(CHECKBOX_OPTIONS.get(cat_name, []))
            self._select_90_per_page()

            entries = self._collect_prices(cat_name)
            self._save_to_csv(csv_code=cat_code, rows=entries)

            logger.info(f"[{cat_name}] 완료 ({len(entries):,}개)")

        except Exception as err:
            logger.error(f"[{cat_name}] 실패: {err!r}")
            traceback.print_exc()
        finally:
            self.driver.quit()

    def _click_checkboxes(self, labels: Iterable[str]) -> None:
        """
        리스트 페이지용 필터 적용
        * <div id="extendSearchOptionpriceCompare"> 영역 내부만 다룸
        * 아직 show_sub_item 이 없는 item_dd 중, btn_view_more 버튼이
          존재하는 패널만 클릭해 옵션을 모두 펼친다.
        """
        if not labels:
            return

        # 1) '옵션 전체보기' 버튼
        try:
            self.wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.button__option-all"))
            ).click()
            logger.debug("[옵션 전체보기] 클릭 완료")
        except Exception as e:
            logger.warning("[옵션 전체보기] 클릭 실패 -> 필터 건너뜀: %s", e)
            return

        # 2) <div id="extendSearchOptionpriceCompare"> 컨테이너 한정
        try:
            option_box = self.wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div#extendSearchOptionpriceCompare")
                )
            )
        except TimeoutException:
            logger.warning("[옵션 영역] 탐색 실패 -> 필터 건너뜀")
            return

        # CSS: spec_list > dl.spec_item:not(.spec_item_bg):not(.makerBrandArea) > dd.item_dd:not(.show_sub_item)
        dd_selector = (
            "div.spec_list dl.spec_item:not(.price_item) "
            "> dd.item_dd:not(.show_sub_item)"
        )
        more_rel_selector = "button.btn_spec_view.btn_view_more"

        while True:
            closed_dds = option_box.find_elements(By.CSS_SELECTOR, dd_selector)
            # '더보기' 버튼이 달린 dd 만 필터링
            targets = [dd for dd in closed_dds if dd.find_elements(By.CSS_SELECTOR, more_rel_selector)]

            if not targets:
                break  # 더 이상 펼칠 패널 없음

            for dd in targets:
                try:
                    more_btn = dd.find_element(By.CSS_SELECTOR, more_rel_selector)
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", more_btn)
                    more_btn.click()
                    # dd 에 show_sub_item 붙을 때까지
                    self.wait.until(lambda d, _dd=dd: "show_sub_item" in _dd.get_attribute("class"))
                    # 상품 리스트 오버레이 사라질 때까지
                    self.wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, ".product_list_cover")))
                except (StaleElementReferenceException, ElementClickInterceptedException) as e:
                    logger.debug("[옵션 더보기] 실패", e)
                    continue
                except Exception as e:
                    logger.debug("[옵션 더보기] 예외: %s", e)
                    continue

        # 3) 라벨 체크
        for label in labels:
            try:
                cb = self.wait.until(EC.presence_of_element_located((By.XPATH, f"//label[@title='{label}']/input[@type='checkbox']")))
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cb)
                self.driver.execute_script("arguments[0].click();", cb)
                self.wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, ".product_list_cover")))
                # logger.debug("[필터] '%s' 체크", label)
            except Exception as e:
                logger.debug("[필터] '%s' 실패: %s", label, e)

    # ------- 1 Page Item 90개 설정 ----------
    def _select_90_per_page(self) -> None:
        try:
            self.driver.find_element(By.XPATH, "//option[@value='90']").click()
            self.wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, ".product_list_cover")))
        except Exception as e:
            logger.debug("[페이지당 90개] 설정 실패: %s", e)

    # --------- 가격 수집 ----------------------
    def _collect_prices(self, cat_name: str) -> list[PriceEntry]:
        entries: list[PriceEntry] = []
        page = 1
        container_css = "div.main_prodlist.main_prodlist_list"
        list_css = f"{container_css} ul.product_list"

        while True:
            self.wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, ".product_list_cover")))
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "li[id^='productInfoDetail_']")))
            # Lazy_load 대기
            self._wait_items_stable(list_css)

            items = self.driver.find_elements(By.CSS_SELECTOR, "li[id^='productInfoDetail_']")
            logger.debug("[%s] %d 페이지 아이템 %d개", cat_name, page, len(items))

            for li in items:
                try:
                    pid = li.get_attribute("id").split("_")[1]
                    try:
                        price_txt = li.find_element(By.CSS_SELECTOR, "p.price_sect strong").text.strip()
                        price = int(price_txt.replace(",", "")) if price_txt else None
                    except (NoSuchElementException, ValueError):
                        price = None
                    entries.append(PriceEntry(pid, price))
                except Exception:
                    continue
            try:
                # 현재 페이지 번호 + 1
                # page = int(self.driver.find_element(By.CSS_SELECTOR,".prod_num_nav .num_nav_wrap .num.now_on").text.strip())
                page += 1
                next_btn = self.wait.until(EC.element_to_be_clickable((
                    By.XPATH,
                    f"//a[contains(@onclick, 'movePage({page})')]"
                )))
                next_btn.click()

            except (NoSuchElementException, TimeoutException) as e:
                logger.debug("[%s] 마지막 페이지", cat_name)
                break

            except Exception as e:
                logger.debug("pagination 오류: ", e)
                break

        return entries

    # -------- 행 안정 대기 ---------------------
    def _wait_items_stable(self, list_css: str, timeout: int = 10, interval: float = 0.3):
        end = time.time() + timeout
        prev = -1
        while time.time() < end:
            cur = len(self.driver.find_elements(By.CSS_SELECTOR, f"{list_css} li[id^='productInfoDetail_']"))
            if cur == prev and cur > 0:
                return
            prev = cur
            time.sleep(interval)
        raise TimeoutException("아이템 개수 안정 대기 시간 초과")

    # ------- csv 저장 -------------------
    def _save_to_csv(self, csv_code: str, rows: List[PriceEntry]) -> None:
        raw_dir = BASE_DIR / "data" / "raw" / csv_code
        raw_dir.mkdir(parents=True, exist_ok=True)
        csv_path = raw_dir / f"{csv_code}_price.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.writer(fp)
            writer.writerow(["ID", "Price"])
            writer.writerows(entry.as_row() for entry in rows)


# -------- 멀티 프로세스 진입 -------------
def _worker(cat: Tuple[str, str]) -> None:
    name, code = cat
    PriceCrawler().crawl(name, code)

def main(processes: int = max(cpu_count() // 2, 1)):
    with Pool(processes) as pool:
        pool.map(_worker, CATEGORIES)
    logger.info(" 모든 카테고리 크롤링 완료")

if __name__ == "__main__":
    main()

