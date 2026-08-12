"""
УСТАРЕЛО: не используется в продакшене. Normativ берутся с Диска Битрикс24 (bitrix_disk.py).

Скачивание Excel-вложений из «Отчёты о работе» через Selenium.

Файлы лежат в служебном хранилище timeman (не Диск) —
REST их не отдаёт, поэтому эмулируем действия в браузере.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent / ".env"
_COOKIE_PATH = Path(__file__).resolve().parent / ".bitrix_cookies.json"
_DEFAULT_DOWNLOAD = Path(__file__).resolve().parent / "downloads" / "bitrix_reports"

PORTAL_DEFAULT = "https://akelagroup.bitrix24.ru"
WORK_REPORT_PATH = "/timeman/work_report.php"


def _load_env() -> None:
    load_dotenv(_ENV_PATH, override=True)


def _portal() -> str:
    _load_env()
    return os.getenv("BITRIX_PORTAL", PORTAL_DEFAULT).rstrip("/")


def _download_dir(target_day: date) -> Path:
    _load_env()
    base = Path(os.getenv("BITRIX_DOWNLOAD_DIR", str(_DEFAULT_DOWNLOAD)))
    folder = base / target_day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _headless() -> bool:
    _load_env()
    return os.getenv("BITRIX_HEADLESS", "false").lower() in {"1", "true", "yes"}


def _build_driver(download_dir: Path):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    try:
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Установите зависимости: pip install selenium webdriver-manager"
        ) from exc

    download_dir.mkdir(parents=True, exist_ok=True)
    abs_dir = str(download_dir.resolve())

    options = Options()
    if _headless():
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1400,1000")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--lang=ru-RU")
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": abs_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "plugins.always_open_pdf_externally": True,
        },
    )

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    # enable downloads in headless chrome
    if _headless():
        driver.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": abs_dir},
        )
    return driver


def _save_cookies(driver) -> None:
    cookies = driver.get_cookies()
    _COOKIE_PATH.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_cookies(driver) -> bool:
    if not _COOKIE_PATH.exists():
        return False
    try:
        cookies = json.loads(_COOKIE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False

    driver.get(_portal() + "/")
    time.sleep(1.5)
    for cookie in cookies:
        cookie = dict(cookie)
        cookie.pop("sameSite", None)
        # selenium may reject expiry float
        if "expiry" in cookie:
            try:
                cookie["expiry"] = int(cookie["expiry"])
            except (TypeError, ValueError):
                cookie.pop("expiry", None)
        try:
            driver.add_cookie(cookie)
        except Exception:
            continue
    return True


def _is_logged_in(driver) -> bool:
    url = (driver.current_url or "").lower()
    if any(x in url for x in ("/auth/", "login", "oauth/authorize")):
        return False
    # work report / main after auth usually have bitrix cookies
    names = {c.get("name") for c in driver.get_cookies()}
    return bool(names & {"BITRIX_SM_UIDH", "BITRIX_SM_UIDL", "PHPSESSID", "BITRIX_SM_LOGIN"})


def login_bitrix(driver, timeout_sec: int = 180) -> None:
    """Логин по BITRIX_LOGIN/BITRIX_PASSWORD или ручной вход в открытом окне."""
    _load_env()
    login = (os.getenv("BITRIX_LOGIN") or "").strip()
    password = (os.getenv("BITRIX_PASSWORD") or "").strip()
    portal = _portal()

    if _load_cookies(driver):
        driver.get(portal + WORK_REPORT_PATH)
        time.sleep(3)
        if _is_logged_in(driver) and "auth" not in driver.current_url.lower():
            return

    driver.get(portal + "/")
    time.sleep(2)

    if login and password:
        _try_password_login(driver, login, password)
        time.sleep(3)
        if _is_logged_in(driver):
            _save_cookies(driver)
            return

    # ручной вход: пользователь логинится в окне Chrome
    if _headless():
        raise RuntimeError(
            "Не удалось войти автоматически. "
            "Укажите BITRIX_LOGIN/BITRIX_PASSWORD в .env "
            "или поставьте BITRIX_HEADLESS=false и войдите вручную."
        )

    driver.get(portal + "/")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if _is_logged_in(driver) and "auth" not in (driver.current_url or "").lower():
            _save_cookies(driver)
            return
        time.sleep(1.5)

    raise RuntimeError("Время ожидания входа в Битрикс24 истекло.")


def _try_password_login(driver, login: str, password: str) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    # Bitrix24 login UI меняется — пробуем типовые поля
    email_selectors = [
        "input[name='USER_LOGIN']",
        "input[type='email']",
        "input[name='login']",
        "input#login",
        "input[data-test-id='login']",
    ]
    pass_selectors = [
        "input[name='USER_PASSWORD']",
        "input[type='password']",
        "input[name='password']",
        "input#password",
    ]

    email_el = None
    for sel in email_selectors:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els:
            email_el = els[0]
            break
    if not email_el:
        return

    email_el.clear()
    email_el.send_keys(login)
    email_el.send_keys(Keys.ENTER)
    time.sleep(2)

    pass_el = None
    for sel in pass_selectors:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els:
            pass_el = els[0]
            break
    if not pass_el:
        return

    pass_el.clear()
    pass_el.send_keys(password)
    pass_el.send_keys(Keys.ENTER)
    time.sleep(4)


def _open_work_reports(driver, target_day: date) -> None:
    """Открывает раздел отчётов (не форму «надо сдать», а список для руководителя)."""
    portal = _portal()
    # без date в URL — сначала общий список, потом клик по строке даты
    driver.get(f"{portal}{WORK_REPORT_PATH}")
    time.sleep(4)
    _dismiss_submit_notifications(driver)


def _dismiss_submit_notifications(driver) -> list[str]:
    """
    Закрывает уведомления/попапы «нужно сдать отчёт».
    Нам нужен список уже сданных отчётов по датам, а не форма сдачи.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    msgs: list[str] = []
    # крестики / «Закрыть» / «Позже»
    close_selectors = [
        ".popup-window-close-icon",
        ".side-panel-label-icon-close",
        ".ui-sidepanel-close",
        "[data-id='close']",
        "button.ui-btn-link",
        ".bx-notifier-item-delete",
    ]
    for sel in close_selectors:
        for el in driver.find_elements(By.CSS_SELECTOR, sel)[:5]:
            try:
                if el.is_displayed():
                    el.click()
                    msgs.append(f"Закрыт элемент: {sel}")
                    time.sleep(0.5)
            except Exception:
                continue

    # если открыта личная форма отчёта — уйти на список
    html = (driver.page_source or "").lower()
    if any(x in html for x in ("отправьте отчёт", "написать отчёт", "сдать отчёт", "отправка отчёта")):
        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            time.sleep(0.5)
        except Exception:
            pass
        # перейти снова на work_report без фокуса на свою сдачу
        driver.get(_portal() + WORK_REPORT_PATH)
        time.sleep(3)
        msgs.append("Ушли с формы «надо сдать» обратно к списку отчётов.")

    return msgs


def _date_text_variants(target_day: date) -> list[str]:
    months_ru = [
        "", "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    ]
    months_short = [
        "", "янв", "фев", "мар", "апр", "мая", "июн",
        "июл", "авг", "сен", "окт", "ноя", "дек",
    ]
    d, m, y = target_day.day, target_day.month, target_day.year
    return [
        target_day.strftime("%d.%m.%Y"),  # 06.08.2026
        target_day.strftime("%d.%m.%y"),
        f"{d:02d}.{m:02d}.{y}",
        f"{d}.{m:02d}.{y}",
        f"{d}.{m}.{y}",
        f"{d} {months_ru[m]} {y}",
        f"{d:02d} {months_ru[m]} {y}",
        f"{d} {months_short[m]}",
        target_day.isoformat(),
    ]


def _click_date_report_row(driver, target_day: date) -> tuple[bool, str]:
    """
    Кликает по строке отчёта с нужной датой.
    Именно после этого появляются вложения; дальше надо скроллить вниз.
    """
    from selenium.webdriver.common.by import By

    variants = _date_text_variants(target_day)
    # все кликабельные узлы с текстом
    candidates = driver.find_elements(
        By.CSS_SELECTOR,
        "a, tr, td, div, span, li, button, .main-grid-cell, .ui-sidepanel-content *",
    )

    for el in candidates:
        try:
            text = (el.text or "").strip()
            if not text or len(text) > 80:
                continue
            text_norm = " ".join(text.split()).lower()
            matched = None
            for v in variants:
                if v.lower() in text_norm:
                    matched = v
                    break
            if not matched:
                continue
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.3)
            driver.execute_script("arguments[0].click();", el)
            time.sleep(2.5)
            return True, f"Клик по строке даты «{text[:60]}» (матч: {matched})."
        except Exception:
            continue

    # запасной путь: XPath contains
    for v in variants[:5]:
        try:
            els = driver.find_elements(By.XPATH, f"//*[contains(normalize-space(.), '{v}')]")
            for el in els[:15]:
                try:
                    if not el.is_displayed():
                        continue
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                    driver.execute_script("arguments[0].click();", el)
                    time.sleep(2.5)
                    return True, f"XPath-клик по дате «{v}»."
                except Exception:
                    continue
        except Exception:
            continue

    return False, f"Строка с датой {target_day.strftime('%d.%m.%Y')} не найдена."


def _scroll_down_for_files(driver, steps: int = 12) -> None:
    """После открытия отчёта по дате — идём вниз, где лежат файлы."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    # скролл окна
    for i in range(steps):
        driver.execute_script("window.scrollBy(0, 600);")
        time.sleep(0.35)

    # скролл внутри типичных контейнеров Bitrix (side panel / report body)
    scroll_boxes = driver.find_elements(
        By.CSS_SELECTOR,
        ".side-panel-content, .ui-sidepanel-content, .ui-page-slider-workarea, "
        ".tm-popup-content, .workreport-content, .popup-window, "
        "[class*='scroll'], .main-grid-container",
    )
    for box in scroll_boxes[:8]:
        try:
            for _ in range(8):
                driver.execute_script(
                    "arguments[0].scrollTop = arguments[0].scrollTop + 500;",
                    box,
                )
                time.sleep(0.25)
        except Exception:
            continue

    try:
        body = driver.find_element(By.TAG_NAME, "body")
        for _ in range(6):
            body.send_keys(Keys.PAGE_DOWN)
            time.sleep(0.25)
    except Exception:
        pass


def _click_file_icons(driver) -> int:
    """Кликает по файлам Normativ_*.xlsx / get_attachment в открытом отчёте."""
    from selenium.webdriver.common.by import By

    clicked = 0
    selectors = [
        "a[href*='get_attachment']",
        "a[href*='.xlsx']",
        "a[href*='.xls']",
        "a[title*='xls']",
        "a[title*='xlsx']",
        "a[title*='XLS']",
        "a[title*='Normativ']",
        "a[title*='normativ']",
        ".files-name a",
        ".feed-con-file a",
        ".disk-file-icon",
        "[class*='file'] a",
    ]
    for sel in selectors:
        for el in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                text = (
                    (el.text or "")
                    + " "
                    + (el.get_attribute("title") or "")
                    + " "
                    + (el.get_attribute("href") or "")
                ).lower()
                href = (el.get_attribute("href") or "").lower()
                is_normativ = "normativ" in text
                is_attach = "get_attachment" in href
                is_excel = ".xlsx" in text or ".xls" in text
                if not (is_normativ or is_attach or is_excel):
                    continue
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                driver.execute_script("arguments[0].click();", el)
                clicked += 1
                time.sleep(1.0)
            except Exception:
                continue

    # клик по любым элементам, в тексте которых есть Normativ_
    for el in driver.find_elements(By.XPATH, "//*[contains(translate(., 'NORMATIV', 'normativ'), 'normativ')]"):
        try:
            tag = (el.tag_name or "").lower()
            if tag not in {"a", "span", "div", "td", "li"}:
                continue
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            driver.execute_script("arguments[0].click();", el)
            clicked += 1
            time.sleep(1.0)
        except Exception:
            continue
    return clicked


def _try_set_date_in_ui(driver, target_day: date) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    value_dot = target_day.strftime("%d.%m.%Y")
    value_iso = target_day.isoformat()
    selectors = [
        "input[name='date']",
        "input[name='REPORT_DATE']",
        "input.bx-calendar-field",
        "input[type='date']",
        "input[data-name='date']",
    ]
    for sel in selectors:
        for el in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                el.clear()
                el.send_keys(value_dot if "date" not in (el.get_attribute("type") or "") else value_iso)
                el.send_keys(Keys.ENTER)
                time.sleep(2)
                return
            except Exception:
                continue


def _debug_dump(driver, download_dir: Path, tag: str) -> list[str]:
    """Сохраняет screenshot + HTML для разбора UI."""
    msgs: list[str] = []
    debug_dir = download_dir / "_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%H%M%S")
    html_path = debug_dir / f"{tag}_{stamp}.html"
    png_path = debug_dir / f"{tag}_{stamp}.png"
    try:
        html_path.write_text(driver.page_source or "", encoding="utf-8")
        msgs.append(f"HTML сохранён: {html_path.name}")
    except Exception as exc:
        msgs.append(f"HTML dump fail: {exc}")
    try:
        driver.save_screenshot(str(png_path))
        msgs.append(f"Screenshot: {png_path.name}")
    except Exception as exc:
        msgs.append(f"Screenshot fail: {exc}")
    msgs.append(f"URL: {driver.current_url}")
    title = ""
    try:
        title = driver.title
    except Exception:
        pass
    msgs.append(f"Title: {title}")
    return msgs


def _links_from_page_source(driver) -> list[dict[str, str]]:
    """Достаёт get_attachment / excel из HTML (даже если ссылка не в <a>)."""
    html = driver.page_source or ""
    found: list[dict[str, str]] = []
    seen: set[str] = set()

    patterns = [
        r'https?://[^"\'\s<>]*get_attachment[^"\'\s<>]*',
        r'/bitrix/tools/timeman\.php\?[^"\'\s<>]*get_attachment[^"\'\s<>]*',
        r'https?://[^"\'\s<>]+\.xlsx',
        r'https?://[^"\'\s<>]+\.xls(?:\b|")',
    ]
    portal = _portal()
    for pat in patterns:
        for match in re.findall(pat, html, flags=re.IGNORECASE):
            href = match.rstrip('\\').replace("&amp;", "&")
            if href.startswith("/"):
                href = portal + href
            if href in seen:
                continue
            seen.add(href)
            found.append({"href": href, "text": ""})
    return found


def _collect_attachment_links(driver) -> list[dict[str, str]]:
    """Собирает ссылки get_attachment (и прямые .xlsx/.xls) со страницы."""
    from selenium.webdriver.common.by import By

    links: list[dict[str, str]] = []
    seen: set[str] = set()

    anchors = driver.find_elements(By.CSS_SELECTOR, "a[href], [href], [data-url], [data-href]")
    for a in anchors:
        href = (
            a.get_attribute("href")
            or a.get_attribute("data-url")
            or a.get_attribute("data-href")
            or ""
        )
        text = (a.text or a.get_attribute("title") or "").strip()
        if not href or href in seen:
            continue

        low = href.lower()
        is_attach = "get_attachment" in low or "action=get_attachment" in low
        is_excel = ".xlsx" in low or low.endswith(".xls") or ".xls?" in low
        if not (is_attach or is_excel):
            continue

        seen.add(href)
        links.append({"href": href, "text": text})

    for item in _links_from_page_source(driver):
        if item["href"] not in seen:
            seen.add(item["href"])
            links.append(item)

    return links


def _count_page_signals(driver) -> dict[str, int]:
    """Грубые признаки: есть ли список сотрудников / отчётов на странице."""
    html = (driver.page_source or "").lower()
    return {
        "get_attachment_mentions": html.count("get_attachment"),
        "xlsx_mentions": html.count(".xlsx") + html.count(".xls"),
        "work_report_mentions": html.count("work_report") + html.count("workreport"),
        "timeman_mentions": html.count("timeman"),
    }


def _expand_report_rows(driver) -> int:
    """Кликает по строкам/заголовкам отчётов, чтобы подгрузить вложения."""
    from selenium.webdriver.common.by import By

    click_selectors = [
        "a.tm-workday-info",
        ".tm-popup-report",
        ".js-id-workreport",
        "tr[data-user-id]",
        ".workreport-item",
        ".tm-report-item",
        "a[href*='report']",
        "[data-id][class*='report']",
        ".main-grid-row",
        "tr.main-grid-row",
        ".ui-sidepanel-layout a",
        "a[href*='user_id']",
        "div[onclick*='report']",
        "span[onclick*='report']",
    ]
    clicked = 0
    for sel in click_selectors:
        for el in driver.find_elements(By.CSS_SELECTOR, sel)[:60]:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                driver.execute_script("arguments[0].click();", el)
                clicked += 1
                time.sleep(0.5)
            except Exception:
                continue
            if clicked >= 40:
                return clicked
    return clicked


def _harvest_links_by_opening_rows(driver) -> list[dict[str, str]]:
    """Кликает строки и после каждого клика собирает новые ссылки на вложения."""
    from selenium.webdriver.common.by import By

    all_links: dict[str, dict[str, str]] = {}
    for item in _collect_attachment_links(driver):
        all_links[item["href"]] = item

    row_selectors = [
        "tr.main-grid-row",
        "tr[data-id]",
        "tr[data-user-id]",
        ".main-grid-row-body",
        "a.bx-ui-user-avatar",
        ".ui-grid-tile-item",
    ]
    rows = []
    for sel in row_selectors:
        rows.extend(driver.find_elements(By.CSS_SELECTOR, sel))
    # уникальные элементы
    uniq_rows = []
    seen_ids = set()
    for r in rows:
        try:
            eid = r.id
        except Exception:
            eid = id(r)
        if eid in seen_ids:
            continue
        seen_ids.add(eid)
        uniq_rows.append(r)

    for row in uniq_rows[:50]:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", row)
            driver.execute_script("arguments[0].click();", row)
            time.sleep(1.2)
            for item in _collect_attachment_links(driver):
                all_links[item["href"]] = item
            # закрыть боковую панель ESC
            try:
                from selenium.webdriver.common.keys import Keys

                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass
            time.sleep(0.3)
        except Exception:
            continue

    return list(all_links.values())


def _wait_downloads(download_dir: Path, already: set[str], timeout: int = 60) -> list[Path]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        partial = list(download_dir.glob("*.crdownload")) + list(download_dir.glob("*.tmp"))
        files = [
            p
            for p in download_dir.iterdir()
            if p.is_file() and p.name not in already and not p.name.endswith(".crdownload")
        ]
        if files and not partial:
            return files
        time.sleep(0.5)
    return [
        p
        for p in download_dir.iterdir()
        if p.is_file() and p.name not in already and not p.name.endswith(".crdownload")
    ]


def _safe_name(name: str) -> str:
    name = re.sub(r"[^\w\-. а-яА-ЯёЁ]+", "_", name, flags=re.UNICODE).strip(" ._")
    return name[:80] or "report"


def _ensure_month(driver, target_day: date, messages: list[str]) -> None:
    """Листает месяцы, пока заголовок не совпадёт с нужным."""
    from selenium.webdriver.common.by import By

    months_ru = [
        "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
    ]
    want = f"{months_ru[target_day.month]} {target_day.year}"
    for _ in range(24):
        body = driver.find_element(By.TAG_NAME, "body").text
        if want in body:
            messages.append(f"Месяц на экране: {want}.")
            return
        # вперёд / назад
        rights = driver.find_elements(By.CSS_SELECTOR, ".filter-date-link-right, a[onclick*='changeMonth(1)']")
        lefts = driver.find_elements(By.CSS_SELECTOR, ".filter-date-link-left, a[onclick*='changeMonth(-1)']")
        # грубо: если год меньше — вперёд, иначе назад
        try:
            if str(target_day.year) in body and months_ru[target_day.month] not in body:
                # тот же год, другой месяц
                cur_idx = next((i for i, m in enumerate(months_ru) if m and m in body.split("Рабочие")[0][-80:]), 0)
                btn = rights[0] if target_day.month > cur_idx else lefts[0]
            elif str(target_day.year) > body:
                btn = rights[0]
            else:
                # сравним по тексту года в filter
                import re as _re
                m = _re.search(r"(Январь|Февраль|Март|Апрель|Май|Июнь|Июль|Август|Сентябрь|Октябрь|Ноябрь|Декабрь)\s+(\d{4})", body)
                if not m:
                    btn = lefts[0] if lefts else rights[0]
                else:
                    name, year = m.group(1), int(m.group(2))
                    idx = months_ru.index(name)
                    cur = year * 12 + idx
                    tgt = target_day.year * 12 + target_day.month
                    btn = rights[0] if tgt > cur else lefts[0]
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(2.5)
        except Exception:
            # JS API
            try:
                driver.execute_script("window.BXTMREPORT && window.BXTMREPORT.changeMonth(1);")
                time.sleep(2.5)
            except Exception:
                break
    messages.append(f"Не удалось точно выставить месяц {want}, продолжаем.")


def _disable_statistics(driver, messages: list[str]) -> None:
    """
    При включённой «Статистике» видны %%, а не кликабельные отчёты.
    Нужно выключить, чтобы появился window.SLIDE и ячейки дней.
    """
    from selenium.webdriver.common.by import By

    try:
        checked = driver.execute_script(
            """
            const el = document.getElementById('stats');
            if (!el) return null;
            return !!el.checked;
            """
        )
        if checked is True:
            driver.execute_script(
                """
                const el = document.getElementById('stats');
                el.click();
                """
            )
            messages.append("Выключена «Статистика» — ждём таблицу отчётов…")
            time.sleep(4)
        elif checked is False:
            messages.append("«Статистика» уже выключена.")
        else:
            # fallback click label
            for el in driver.find_elements(By.CSS_SELECTOR, "label[for='stats'], #stats"):
                try:
                    el.click()
                    messages.append("Клик по «Статистика» (fallback).")
                    time.sleep(4)
                    break
                except Exception:
                    continue
    except Exception as exc:
        messages.append(f"Не удалось переключить статистику: {exc}")


def _wait_for_slides(driver, timeout: int = 30) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        n = driver.execute_script(
            "return (window.SLIDE && window.SLIDE.length) ? window.SLIDE.length : 0;"
        )
        if n and int(n) > 0:
            return int(n)
        time.sleep(0.5)
    return int(
        driver.execute_script(
            "return (window.SLIDE && window.SLIDE.length) ? window.SLIDE.length : 0;"
        )
        or 0
    )


def _slides_for_day(driver, target_day: date) -> list[dict[str, Any]]:
    """
    Берёт window.SLIDE и оставляет отчёты, чья ячейка в колонке нужного дня.
    """
    day_num = target_day.day
    raw = driver.execute_script(
        """
        const dayNum = String(arguments[0]);
        // индекс колонки дня по заголовкам
        const titles = Array.from(document.querySelectorAll('.bx-tm-day-title'));
        let dayCol = -1;
        titles.forEach((el, idx) => {
          if ((el.textContent || '').trim() === dayNum) dayCol = idx;
        });

        const slides = (window.SLIDE || []).map((s, i) => {
          let cellIndex = null;
          try { cellIndex = s.oCell ? s.oCell.cellIndex : null; } catch (e) {}
          let text = '';
          try { text = s.oCell ? (s.oCell.innerText || '') : ''; } catch (e) {}
          return {
            i,
            report: s.report,
            user_id: s.user_id,
            cellIndex,
            text: text.slice(0, 80),
          };
        });
        return { dayCol, slides, titles: titles.map(t => (t.textContent||'').trim()) };
        """,
        day_num,
    ) or {}

    day_col = raw.get("dayCol", -1)
    slides = raw.get("slides") or []
    titles = raw.get("titles") or []

    # колонка дня: у заголовка cellIndex в той же таблице
    # иногда cellIndex ячейки отчёта = dayCol (или +offset для name col)
    selected = []
    for s in slides:
        ci = s.get("cellIndex")
        if day_col >= 0 and ci is not None:
            # ячейка можетspan - cellIndex равен старту периода; подходит если день попадает в colspan
            # упрощение: точное совпадение индекса ИЛИ заголовок дня рядом
            if int(ci) == int(day_col):
                selected.append(s)
                continue
        # fallback: если dayCol не определён — берём все (лучше все, чем ноль)
    if not selected and slides and day_col < 0:
        selected = slides
    if not selected and slides:
        # второй fallback: кликаем все цветные отчёты — но пометим warning
        selected = slides

    return {
        "day_col": day_col,
        "titles": titles,
        "all_count": len(slides),
        "selected": selected,
    }


def _open_report_slider(driver, user_id: int, report_id: int) -> None:
    driver.execute_script(
        """
        const uid = Number(arguments[0]);
        const rid = Number(arguments[1]);
        if (window.BX && BX.StartSlider) {
          BX.StartSlider(uid, rid);
        } else if (window.BXTMREPORT && BXTMREPORT.ShowNewReport) {
          BXTMREPORT.ShowNewReport(uid, rid);
        } else {
          // клик по ячейке из SLIDE
          const hit = (window.SLIDE || []).find(s => Number(s.report) === rid && Number(s.user_id) === uid);
          if (hit && hit.oCell) hit.oCell.click();
        }
        """,
        int(user_id),
        int(report_id),
    )
    time.sleep(2.5)


def _close_report_slider(driver) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    for sel in [
        ".side-panel-close",
        ".ui-sidepanel-close",
        ".popup-window-close-icon",
        ".side-panel-label-icon-close",
    ]:
        for el in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                if el.is_displayed():
                    el.click()
                    time.sleep(0.4)
                    return
            except Exception:
                continue
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(0.4)
    except Exception:
        pass


def download_work_report_excels(target_day: date) -> dict[str, Any]:
    """
    Отчёты о работе (таблица дней):
    1) выключить «Статистика»
    2) открыть ячейки отчётов за нужный день (BX.StartSlider)
    3) вниз к файлам Normativ_*.xlsx и скачать
    """
    download_dir = _download_dir(target_day)
    messages: list[str] = []
    before = {p.name for p in download_dir.iterdir() if p.is_file()}

    driver = _build_driver(download_dir)
    downloaded: list[Path] = []
    links: list[dict[str, str]] = []
    seen_href: set[str] = set()

    try:
        login_bitrix(driver)
        messages.append("Вход в Битрикс24 выполнен.")

        driver.get(_portal() + WORK_REPORT_PATH)
        time.sleep(5)
        for m in _dismiss_submit_notifications(driver):
            messages.append(m)

        _ensure_month(driver, target_day, messages)
        _disable_statistics(driver, messages)

        # обойти все страницы таблицы (Страницы: 1 2 3 4…)
        page = 1
        max_pages = 15
        all_selected: list[dict[str, Any]] = []
        seen_reports: set[int] = set()

        while page <= max_pages:
            n_slides = _wait_for_slides(driver, timeout=20 if page == 1 else 15)
            messages.append(f"Страница {page}: SLIDE={n_slides}.")
            info = _slides_for_day(driver, target_day)
            for s in info["selected"]:
                rid = int(s["report"])
                if rid in seen_reports:
                    continue
                seen_reports.add(rid)
                all_selected.append(s)
            messages.append(
                f"  день {target_day.day}: колонка={info['day_col']}, "
                f"на странице={len(info['selected'])}, накоплено={len(all_selected)}."
            )

            # следующая страница
            moved = driver.execute_script(
                """
                const next = Number(arguments[0]) + 1;
                const links = Array.from(document.querySelectorAll('a[onclick*=\"BXTMREPORT.Page\"]'));
                const hit = links.find(a => (a.getAttribute('onclick')||'').includes('Page('+next+')'));
                if (hit) { hit.click(); return true; }
                if (window.BXTMREPORT && next <= 20) {
                  try { window.BXTMREPORT.Page(next); return true; } catch(e) { return false; }
                }
                return false;
                """,
                page,
            )
            if not moved:
                break
            page += 1
            time.sleep(3.5)

        selected = all_selected
        messages.append(f"Всего отчётов за день к открытию: {len(selected)}.")

        if not selected:
            messages.append("Нет ячеек отчётов — сохраняю debug.")
            messages.extend(_debug_dump(driver, download_dir, "no_slides"))
        else:
            from selenium.webdriver.common.by import By

            for _ in range(8):
                try:
                    arrows = driver.find_elements(
                        By.CSS_SELECTOR,
                        "#tm_report_scroller_right, .tm-report-scroller-right",
                    )
                    if arrows:
                        driver.execute_script("arguments[0].click();", arrows[0])
                        time.sleep(0.2)
                except Exception:
                    break

        for idx, item in enumerate(selected, start=1):
            uid = int(item["user_id"])
            rid = int(item["report"])
            messages.append(f"[{idx}/{len(selected)}] Открываю report={rid} user={uid}…")
            try:
                _open_report_slider(driver, uid, rid)
            except Exception as exc:
                messages.append(f"  не открылся: {exc}")
                continue

            # дождаться попапа отчёта
            ready = False
            for _ in range(20):
                ready = driver.execute_script(
                    """
                    const pop = document.querySelector('.popup-window.--open [id*=\"popup_report\"], .popup-window.--open .report-popup-main-table, .report-popup-main-table');
                    return !!pop;
                    """
                )
                if ready:
                    break
                time.sleep(0.4)
            if not ready:
                messages.append("  попап не появился.")
                continue

            _scroll_down_for_files(driver, steps=10)
            time.sleep(1.2)

            page_links = _collect_attachment_links(driver)
            # также любые a.upload-file-name
            from selenium.webdriver.common.by import By

            for a in driver.find_elements(By.CSS_SELECTOR, "a.upload-file-name, a[href*='get_attachment']"):
                href = a.get_attribute("href") or ""
                text = (a.text or "").strip()
                if href and href not in seen_href:
                    page_links.append({"href": href, "text": text})

            normativ_links = [
                L
                for L in page_links
                if "normativ" in (L.get("text") or "").lower()
                or "normativ" in (L.get("href") or "").lower()
                or "get_attachment" in (L.get("href") or "").lower()
            ]

            if not normativ_links and not page_links:
                messages.append("  файлов во вложении нет (только «Загрузить файл»).")
            else:
                messages.append(
                    f"  ссылок: {len(page_links)}, из них на скачивание: {len(normativ_links) or len(page_links)}."
                )

            file_clicks = _click_file_icons(driver)
            if file_clicks:
                messages.append(f"  кликов по файлам: {file_clicks}")
                time.sleep(1.5)

            for link in (normativ_links or page_links):
                href = link["href"]
                if href in seen_href:
                    continue
                seen_href.add(href)
                links.append(link)

            for p in download_dir.iterdir():
                if p.is_file() and p.name not in before and p.name not in {x.name for x in downloaded}:
                    if not p.name.endswith(".crdownload"):
                        downloaded.append(p)

            _close_report_slider(driver)
            time.sleep(0.6)

        messages.append(f"Собрано ссылок на вложения: {len(links)}.")

        for idx, item in enumerate(links, start=1):
            href = item["href"]
            low = href.lower()
            if any(ext in low for ext in (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".doc")):
                if ".xlsx" not in low and ".xls" not in low and "get_attachment" not in low:
                    continue

            existing = {p.name for p in download_dir.iterdir() if p.is_file()}
            try:
                driver.get(href)
            except Exception as exc:
                messages.append(f"Скачивание #{idx} fail: {exc}")
                continue

            new_files = _wait_downloads(download_dir, existing, timeout=45)
            for fpath in new_files:
                qs = parse_qs(urlparse(href).query)
                fid = (qs.get("fid") or ["?"])[0]
                report_id = (qs.get("report_id") or ["?"])[0]
                user_id = (qs.get("user_id") or ["?"])[0]
                suffix = fpath.suffix.lower() or ".bin"
                # сохранить оригинальное имя если Normativ
                orig = fpath.name
                if "normativ" in orig.lower():
                    new_name = orig
                else:
                    new_name = _safe_name(
                        f"{target_day.isoformat()}_u{user_id}_r{report_id}_f{fid}_{fpath.stem}"
                    ) + suffix
                target = download_dir / new_name
                try:
                    if target.exists() and target != fpath:
                        target.unlink()
                    fpath.rename(target)
                    downloaded.append(target)
                except Exception:
                    downloaded.append(fpath)
            time.sleep(0.5)

        excel_files = sorted(
            {
                *downloaded,
                *[
                    p
                    for p in download_dir.iterdir()
                    if p.is_file()
                    and p.suffix.lower() in {".xlsx", ".xls"}
                    and p.name not in before
                ],
            }
        )
        normativ = [p for p in excel_files if "normativ" in p.name.lower()]
        if normativ:
            messages.append(f"Из них Normativ_*: {len(normativ)}.")
            excel_files = normativ
        messages.append(f"Скачано Excel-файлов: {len(excel_files)}.")

        if not excel_files:
            messages.extend(_debug_dump(driver, download_dir, "no_excel_final"))

        return {
            "dir": download_dir,
            "files": excel_files,
            "links_found": len(links),
            "messages": messages,
        }
    finally:
        try:
            _save_cookies(driver)
        except Exception:
            pass
        driver.quit()
