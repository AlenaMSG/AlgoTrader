import time
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

EMAIL    = "alenamaria86@gmail.com"
PASSWORD = "Alena.1pxp.p"

BASE      = Path(__file__).parent / "Readme"
OUT_FILE  = BASE / "config.txt"
MFA_FILE  = BASE / "mfa_code.txt"
LOG_FILE  = BASE / "script_log.txt"

BASE.mkdir(exist_ok=True)

_log = open(LOG_FILE, "w", encoding="utf-8", buffering=1)

def log(msg):
    print(msg, flush=True)
    _log.write(msg + "\n")
    _log.flush()


def poll_for_file(path, timeout_s=300):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if path.exists():
            code = path.read_text().strip()
            path.unlink()
            return code
        time.sleep(2)
    return None


def shot(page, name):
    page.screenshot(path=f"Readme/{name}.png")
    log(f"  [img] {name}.png  url={page.url}")


def extract_keys(page):
    content = page.content()
    api_key = None
    secret_key = None
    hits = re.findall(r'PK[A-Z0-9]{8,40}', content)
    if hits:
        api_key = hits[0]
    if api_key:
        idx = content.find(api_key)
        window = content[max(0, idx - 200):idx + 800]
        for c in re.findall(r'[A-Za-z0-9]{32,64}', window):
            if c != api_key and not c.startswith("PK"):
                secret_key = c
                break
        if not secret_key:
            for sel in ['input[readonly]', 'input[type="text"]', 'code', 'pre']:
                for el in page.query_selector_all(sel):
                    try:
                        txt = (el.get_attribute("value") or el.inner_text() or "").strip()
                        if re.match(r'^[A-Za-z0-9]{30,64}$', txt) and txt != api_key:
                            secret_key = txt
                            break
                    except:
                        pass
                if secret_key:
                    break
    return api_key, secret_key


def click_regen(page):
    for txt in ["Regenerate", "View", "Generate API Key", "Generate", "Create"]:
        try:
            btn = page.query_selector(f'button:has-text("{txt}")')
            if btn and btn.is_visible():
                log(f"  click '{txt}'")
                btn.click()
                time.sleep(3)
                return True
        except:
            pass
    return False


def get_alpaca_keys():
    with sync_playwright() as p:
        # headless=True para que funcione en background
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()

        # --- Login ---
        log("PASO 1: login")
        page.goto("https://app.alpaca.markets/login")
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2)
        try:
            page.click('button:has-text("Accept")', timeout=2000)
            time.sleep(1)
        except:
            pass
        page.fill('input[name="email"]', EMAIL)
        time.sleep(0.4)
        page.fill('input[name="password"]', PASSWORD)
        time.sleep(0.4)
        try:
            page.click('button:has-text("Continue")', timeout=3000)
        except:
            try:
                page.click('button[type="submit"]', timeout=2000)
            except:
                page.press('input[name="password"]', "Enter")
        time.sleep(5)

        # --- MFA ---
        log("PASO 2: MFA check")
        otp_el = None
        for sel in [
            'input[name="code"]', 'input[name="otp"]', 'input[name="mfa"]',
            'input[autocomplete="one-time-code"]', 'input[inputmode="numeric"]',
        ]:
            try:
                el = page.wait_for_selector(sel, timeout=3000)
                if el and el.is_visible():
                    otp_el = el
                    break
            except:
                pass

        if otp_el:
            log(">>> 2FA REQUERIDO - escribe en el chat de Claude:")
            log("    ! echo TU_CODIGO > C:\\proyectos\\AlgoTrader\\Readme\\mfa_code.txt")
            log("Esperando hasta 5 minutos...")
            code = poll_for_file(MFA_FILE, timeout_s=300)
            if not code:
                log("Timeout MFA. Abortando.")
                browser.close()
                _log.close()
                return
            log(f"  codigo: {code}")

            # Detectar si hay 6 cajas individuales (una por digito)
            all_inputs = page.query_selector_all(
                'input[type="tel"], input[type="number"], input[type="text"][maxlength="1"], input[inputmode="numeric"]'
            )
            single_inputs = [el for el in all_inputs if el.is_visible()]
            log(f"  inputs MFA visibles: {len(single_inputs)}")

            # Clic en el primer input y escribir todos los digitos con keyboard
            otp_el.click()
            time.sleep(0.3)
            page.keyboard.type(code, delay=120)

            time.sleep(0.8)
            # Buscar boton Verify o Submit (usar page.click, no otp_el que puede estar detached)
            submitted = False
            for btn_txt in ["Verify", "Continue", "Submit"]:
                try:
                    page.click(f'button:has-text("{btn_txt}")', timeout=3000)
                    submitted = True
                    log(f"  clicked '{btn_txt}'")
                    break
                except:
                    pass
            if not submitted:
                page.keyboard.press("Enter")
            time.sleep(5)
        else:
            log("  No 2FA detectado")

        shot(page, "s1_after_login")
        log(f"URL post-login: {page.url}")

        # --- Intento 1: paper settings/api ---
        log("INTENTO 1: paper/settings/api")
        page.goto("https://app.alpaca.markets/paper/settings/api",
                  wait_until="networkidle", timeout=20000)
        time.sleep(5)
        shot(page, "s2_settings_api")
        log(f"  url: {page.url}")
        # Esperar a que aparezca algun elemento de la pagina
        try:
            page.wait_for_selector('button, h1, h2, [class*="key"], [class*="api"]',
                                   timeout=8000)
        except:
            pass
        time.sleep(3)
        shot(page, "s2b_settings_api_loaded")
        click_regen(page)
        api_key, secret_key = extract_keys(page)

        # --- Intento 2: Paper Trading dropdown -> Account Management ---
        if not api_key:
            log("INTENTO 2: Paper Trading dropdown")
            try:
                page.goto("https://app.alpaca.markets/brokerage/new-account")
                time.sleep(2)
                page.click('button:has-text("Paper Trading")', timeout=3000)
                time.sleep(2)
                shot(page, "s3_pt_dropdown")
                page.click('button:has-text("Account Management")', timeout=3000)
                time.sleep(3)
                shot(page, "s4_acct_mgmt")
                log(f"  url: {page.url}")
                click_regen(page)
                api_key, secret_key = extract_keys(page)
            except Exception as e:
                log(f"  error: {e}")

        # --- Intento 3: gear icon (coordenadas) ---
        if not api_key:
            log("INTENTO 3: gear icon")
            try:
                page.goto("https://app.alpaca.markets/brokerage/new-account")
                time.sleep(2)
                # El engranaje esta en la parte inferior del sidebar ~(30, 855)
                page.mouse.click(30, 855)
                time.sleep(3)
                shot(page, "s5_gear")
                log(f"  url tras gear: {page.url}")
                click_regen(page)
                api_key, secret_key = extract_keys(page)
            except Exception as e:
                log(f"  error: {e}")

        # --- Intento 4: todos los hrefs de la pagina ---
        if not api_key:
            log("INTENTO 4: explorando todos los links")
            page.goto("https://app.alpaca.markets/brokerage/new-account")
            time.sleep(2)
            # Guardar HTML completo
            html = page.content()
            (BASE / "page_debug.html").write_text(html, encoding="utf-8")
            log("  HTML guardado en Readme/page_debug.html")
            # Listar todos los hrefs
            for el in page.query_selector_all('a[href]'):
                try:
                    href = el.get_attribute("href")
                    txt = el.inner_text().strip()[:40]
                    log(f"  LINK: {href}  [{txt}]")
                except:
                    pass
            # Listar botones
            for el in page.query_selector_all('button'):
                try:
                    txt = el.inner_text().strip()
                    if txt:
                        log(f"  BTN: {txt[:60]}")
                except:
                    pass

        shot(page, "s6_final")
        browser.close()

        if api_key:
            lines = f"API_KEY={api_key}\n"
            if secret_key:
                lines += f"SECRET_KEY={secret_key}\n"
            OUT_FILE.write_text(lines)
            log(f"OK guardado en {OUT_FILE}")
            log(lines)
        else:
            log("FAIL: keys no encontradas.")
            log("Revisa Readme/script_log.txt y Readme/page_debug.html")

    _log.close()


if __name__ == "__main__":
    get_alpaca_keys()
