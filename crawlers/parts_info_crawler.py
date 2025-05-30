# -*- coding: utf-8 -*-
"""
Danawa 가상견적 페이지 크롤러
* 단일 카테고리 → Product 리스트 수집
* 다중 프로세스 병렬 처리 지원
"""

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
)

# 로그 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)                     # 필요 시 INFO·WARNING 등으로 조정
_stream = logging.StreamHandler()
_stream.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.addHandler(_stream)

# -------------------------------------------------------
# 전역 상수
# -------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DRIVER_PATH = BASE_DIR / "driver" / "chromedriver.exe"

DANAWA_VE_URL = "https://shop.danawa.com/virtualestimate/?controller=estimateMain&methods=index&marketPlaceSeq=16"

# 화면 탭 이름, 파일명 매핑
CATEGORIES: list[tuple[str, str]] = [
        ("CPU", "CPU"),
        ("쿨러/튜닝", "Cooler"),
        ("메인보드", "Motherboard"),
        ("메모리", "Memory"),
        ("그래픽카드", "VGA"),
        ("SSD", "SSD"),
        ("HDD", "HDD"),
        ("케이스", "Case"),
        ("파워", "PSU"),
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
    "메모리": ["데스크탑용", "DDR5", "DDR4"],
    "그래픽카드": [],
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
# -------------------------------------------------------
# 데이터 모델
# -------------------------------------------------------
@dataclass(slots=True)
class Product:
    pid: str
    name: str
    spec: str
    image_url: str
    product_url: str

    def as_csv_row(self) -> list[str]:
        return [self.pid, self.name, self.spec, self.image_url, self.product_url]

# ---------- 크롤러 ----------------------------------------
class VirtualEstimateCrawler:
    """단일 WebDriver로 하나의 카테고리를 수집"""

    # -------- Selenium 초기화 ---------------------------
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
    def crawl(self, category_name: str, category_code: str) -> None:
        """지정 카테고리를 크롤링하고 CSV로 저장"""
        try:
            print(f"[{category_name}] 크롤링 시작")
            self.driver.get(DANAWA_VE_URL)

            # 1. 탭 이동
            self._click_category_tab(category_name)

            # 2. 옵션 필터링
            self._click_checkboxes(CHECKBOX_OPTIONS.get(category_name, []))

            # 3. 제품 목록 수집
            products = self._collect_products(category_name)

            # 4. CSV 저장
            self._save_to_csv(products, category_code)
            print(f"[{category_name}] 완료 ({len(products):,}개)")

        except Exception as err:  # 예상치 못한 예외도 모두 캡처
            print(f"[{category_name}] 크롤링 실패: {err!r}")
            traceback.print_exc()
        finally:
            self.driver.quit()

    # -------- 내부 동작 -------------------------------------
    def _click_category_tab(self, tab_name: str) -> None:
        tab_btn = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, f"//a[@class='pd_item_title' and normalize-space(text())='{tab_name}']")
            )
        )
        tab_btn.click()
        # 로딩 오버레이가 사라질 때까지 대기
        self.wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, ".product_list_cover")))

    def _click_checkboxes(self, labels: Iterable[str]) -> None:
        """
        옵션 패널 열기 → '더보기' 전부 펼치기 → 원하는 체크박스 클릭
        실패해도 치명적이지 않으므로 WARNING 수준만 기록
        """
        if not labels:
            return

        # 전체보기 열기
        try:
            self.wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.search_option_all"))
            ).click()
        except Exception as e:
            print("[옵션 전체보기] 버튼 클릭 실패 -> 필터 건너뜀: ", e)
            return

        # ── 2) '더보기' 펼치기 루프 ───────────────────────────────────────────
        # 조건: (a) parent .search_cate_contents NOT .open
        #       (b) 그 안에 button.btn_item_more 가 존재
        # CSS 선택자:  div.search_cate_contents:not(.open) button.btn_item_more

        more_selector = "div.search_cate_contents:not(.open) button.btn_item_more"
        while True:
            try:
                more_btn = self.wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, more_selector)),
                    # 위 조건을 만족하는 버튼이 더 이상 없으면 TimeoutException
                )
                # 스크롤 후 클릭
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", more_btn
                )
                more_btn.click()

                # 클릭된 버튼이 포함된 영역이 open 클래스를 얻을 때까지 대기
                parent_panel = more_btn.find_element(By.XPATH,
                                                     "./ancestor::div[contains(@class,'search_cate_contents')]")
                self.wait.until(lambda d: "open" in parent_panel.get_attribute("class"))

                # 클릭 직후 DOM 리렌더링 → stale 방지
                self.wait.until(EC.staleness_of(more_btn))
                logger.debug("[옵션 더보기] 패널 하나 펼침")

            except TimeoutException:
                # 조건을 만족하는 버튼이 없으면 모든 패널이 펼쳐진 상태
                logger.debug("[옵션 더보기] 남은 버튼 없음 → 루프 종료")
                break
            except StaleElementReferenceException:
                # 리렌더링 타이밍에 발생 -> 루프 재시작
                continue
            except Exception as e:
                logger.debug("[옵션 더보기] 클릭 예외: %s", e)
                continue

        # 실제 체크박스 클릭
        for label in labels:
            try:
                check = self.wait.until(
                    EC.presence_of_element_located(
                        (
                            By.XPATH,
                            f"//input[@type='checkbox' and normalize-space(@data)='{label}']",
                        )
                    )
                )
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", check)
                time.sleep(0.15)  # 스크롤 안정화
                self.driver.execute_script("arguments[0].click();", check)
                self.wait.until(
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, ".product_list_cover"))
                )
                logger.debug("[필터] '%s' 체크 완료", label)
            except Exception as e:
                logger.debug("[필터] '%s' 체크 실패: %s", label, e)


    def _collect_products(self, category_name: str) -> list[Product]:
        products = []
        page = 1
        container_css = "div.list_tbl_wrap.admd_tbl_wrap.estimate_renew_list"
        table_css = f"{container_css} div.scroll_box > table.tbl_list"

        old_table = None  # staleness 감시용

        while True:
            # 1) 이전 테이블이 있으면, staleness 될 때까지 대기
            if old_table is not None:
                self.wait.until(EC.staleness_of(old_table))

            # 2) 새 테이블 ready 대기 + 행 개수 안정 대기
            table = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, table_css))
            )
            self._wait_rows_stable(table_css)

            rows = self.driver.find_elements(By.CSS_SELECTOR, f"{table_css} tbody tr")
            logger.debug(f"[{category_name}] {page}페이지 행 {len(rows)}개 발견")

            for idx in range(len(rows)):
                try:
                    row = rows[idx]  # 인덱스로 재확보하면 stale 최소화
                    pid = row.get_attribute("class").split("_")[-1]
                    name = row.find_element(
                        By.CSS_SELECTOR, "td.title_price p.subject a"
                    ).text.strip()
                    image = (
                        row.find_element(By.CSS_SELECTOR, "td.goods_img img")
                        .get_attribute("src")
                        .split("?")[0]
                    )
                    spec = (
                        row.find_element(By.CSS_SELECTOR, "td.title_price div.spec_wrap a")
                        .text.replace("\n", " / ").strip()
                    )
                    products.append(
                        Product(pid, name, spec, image, f"https://prod.danawa.com/info/?pcode={pid}")
                    )
                except StaleElementReferenceException:
                    # ------- 재시도 로직 (동일 코드) --------------
                    try:
                        fresh_row = self.driver.find_elements(
                            By.CSS_SELECTOR, f"{table_css} tbody tr"
                        )[idx]
                        pid = fresh_row.get_attribute("class").split("_")[-1]
                        name = fresh_row.find_element(
                            By.CSS_SELECTOR, "td.title_price p.subject a"
                        ).text.strip()
                        image = (
                            fresh_row.find_element(By.CSS_SELECTOR, "td.goods_img img")
                            .get_attribute("src")
                            .split("?")[0]
                        )
                        spec = (
                            fresh_row.find_element(By.CSS_SELECTOR, "td.title_price div.spec_wrap a")
                            .text.replace("\n", " / ").strip()
                        )
                        products.append(
                            Product(pid, name, spec, image, f"https://prod.danawa.com/info/?pcode={pid}")
                        )
                        logger.debug(f"{pid} (retry) 수집")
                    except Exception as retry_err:
                        logger.debug(f"행 재시도 실패: {retry_err!r}")
                        continue
                except Exception as any_err:
                    logger.debug(f"행 스킵: {any_err!r}")
                    continue

            # 3) 다음 페이지 이동
            try:
                next_btn = self.driver.find_element(
                    By.CSS_SELECTOR,
                    ".paging_estimate li.pagination-box__item.pagination--now + li a",
                )
                next_btn.click()
                page += 1
                old_table = table  # 방금 사용한 테이블을 staleness 대상 지정
            except (NoSuchElementException, TimeoutException):
                break  # 마지막 페이지

        return products

    def _wait_rows_stable(self, table_css: str, timeout: int = 10, interval: float = 0.3):
        """
        테이블 tr 개수가 '두 번 연속 동일'할 때까지 대기.
        Lazy-loading 이 끝났다고 간주.
        """
        end_time = time.time() + timeout
        prev_cnt = -1
        while time.time() < end_time:
            curr_cnt = len(
                self.driver.find_elements(By.CSS_SELECTOR, f"{table_css} tbody tr")
            )
            if curr_cnt == prev_cnt and curr_cnt > 0:
                return
            prev_cnt = curr_cnt
            time.sleep(interval)
        raise TimeoutException("행 개수 안정 대기 timeout")

    def _save_to_csv(self, products: List[Product], code: str) -> None:
        raw_dir = BASE_DIR / "data" / "raw" / code
        raw_dir.mkdir(parents=True, exist_ok=True)

        csv_path = raw_dir / f"{code}_info.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.writer(fp)
            writer.writerow(["ID", "Name", "Spec", "ImageURL", "ProductURL"])
            writer.writerows(prod.as_csv_row() for prod in products)

# -------------------------------------------------------
# 멀티 프로세싱 진입
# -------------------------------------------------------
def _worker(category: Tuple[str, str]) -> None:
    name, code = category
    VirtualEstimateCrawler().crawl(name, code)

def main(processes: int = max(cpu_count() // 2, 1)) -> None:
    with Pool(processes) as pool:
        pool.map(_worker, CATEGORIES)
    print("모든 카테고리 크롤링이 완료되었습니다.")

if __name__ == "__main__":
    main()
