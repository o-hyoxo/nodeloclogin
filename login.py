import os
import time
import sys

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


NODELOC_URL = "https://www.nodeloc.com"
LOGIN_URL = "https://www.nodeloc.com/login"

USERNAME = os.getenv("NODELOC_USERNAME")
PASSWORD = os.getenv("NODELOC_PASSWORD")


def build_driver():
    chrome_options = Options()

    # GitHub Actions 推荐参数
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    # 尽量降低 headless 被识别概率
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    chrome_options.add_experimental_option(
        "excludeSwitches",
        ["enable-automation"]
    )
    chrome_options.add_experimental_option(
        "useAutomationExtension",
        False
    )

    driver = webdriver.Chrome(options=chrome_options)

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """
        },
    )

    return driver


def safe_text(value):
    return value if value else ""


def debug_button(button, prefix="按钮状态"):
    cls = safe_text(button.get_attribute("class"))
    title = safe_text(button.get_attribute("title"))
    aria = safe_text(button.get_attribute("aria-label"))
    disabled = safe_text(button.get_attribute("disabled"))

    print(f"{prefix}:")
    print(f"  class      = {cls}")
    print(f"  title      = {title}")
    print(f"  aria-label = {aria}")
    print(f"  disabled   = {disabled}")


def is_checked_in(button):
    cls = safe_text(button.get_attribute("class"))
    title = safe_text(button.get_attribute("title"))
    aria = safe_text(button.get_attribute("aria-label"))

    return (
        "checked-in" in cls
        or "已经签到" in title
        or "已经签到" in aria
        or "已签到" in title
        or "已签到" in aria
    )


def wait_for_page_ready(driver, timeout=20):
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def login(driver):
    if not USERNAME or not PASSWORD:
        print("❌ 请设置环境变量 NODELOC_USERNAME 和 NODELOC_PASSWORD")
        sys.exit(1)

    print("正在访问 NodeLoc 首页...")
    driver.get(NODELOC_URL)
    wait_for_page_ready(driver)

    wait = WebDriverWait(driver, 20)

    # 如果已经登录，页面通常会出现头像/用户菜单/签到按钮
    if driver.find_elements(By.CSS_SELECTOR, ".checkin-button"):
        print("✅ 检测到已登录状态，跳过登录。")
        return

    print("正在打开登录页面...")
    driver.get(LOGIN_URL)
    wait_for_page_ready(driver)

    # Discourse 登录页常见输入框
    username_selectors = [
        "#login-account-name",
        "input[name='login']",
        "input[name='username']",
        "input[type='text']",
        "input[type='email']",
    ]

    password_selectors = [
        "#login-account-password",
        "input[name='password']",
        "input[type='password']",
    ]

    username_input = None
    password_input = None

    for selector in username_selectors:
        elems = driver.find_elements(By.CSS_SELECTOR, selector)
        if elems:
            username_input = elems[0]
            break

    for selector in password_selectors:
        elems = driver.find_elements(By.CSS_SELECTOR, selector)
        if elems:
            password_input = elems[0]
            break

    if not username_input or not password_input:
        print("❌ 未找到登录输入框。当前页面标题：", driver.title)
        driver.save_screenshot("login_page_error.png")
        sys.exit(1)

    username_input.clear()
    username_input.send_keys(USERNAME)

    password_input.clear()
    password_input.send_keys(PASSWORD)

    login_button_selectors = [
        "#login-button",
        "button.btn-primary",
        "button[type='submit']",
        ".login-button",
    ]

    login_button = None
    for selector in login_button_selectors:
        elems = driver.find_elements(By.CSS_SELECTOR, selector)
        visible = [e for e in elems if e.is_displayed() and e.is_enabled()]
        if visible:
            login_button = visible[0]
            break

    if not login_button:
        print("❌ 未找到登录按钮。")
        driver.save_screenshot("login_button_error.png")
        sys.exit(1)

    print("找到登录按钮，正在登录...")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", login_button)
    time.sleep(0.5)
    login_button.click()

    # 等待登录成功：出现签到按钮或页面跳转后出现用户区
    try:
        wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".checkin-button, .header-dropdown-toggle, .current-user")
            )
        )
        print("✅ 登录成功！")
    except Exception:
        print("❌ 登录后未检测到成功状态。")
        driver.save_screenshot("login_failed.png")
        sys.exit(1)


def find_checkin_button(driver):
    wait = WebDriverWait(driver, 20)

    print("🔍 正在寻找签到按钮...")

    # 先回首页，确保 header 已加载
    driver.get(NODELOC_URL)
    wait_for_page_ready(driver)
    time.sleep(3)

    selectors = [
        "li.checkin-icon button.checkin-button",
        "button.checkin-button",
        ".header-dropdown-toggle.checkin-icon button",
        "button[title*='签到']",
        "button[aria-label*='签到']",
        "button[title*='已经签到']",
        "button[aria-label*='已经签到']",
    ]

    last_error = None

    for selector in selectors:
        try:
            print(f"尝试选择器: {selector}")
            button = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            debug_button(button, "找到签到按钮")
            return button
        except Exception as e:
            last_error = e

    print("❌ 未找到签到按钮。")
    driver.save_screenshot("checkin_button_not_found.png")
    if last_error:
        print("最后一次错误：", repr(last_error))
    sys.exit(1)


def click_checkin_button(driver, button):
    wait = WebDriverWait(driver, 20)

    if is_checked_in(button):
        print("✅ 今天已经签到过了，无需重复点击。")
        return True

    print("👉 检测到尚未签到，准备点击签到按钮...")

    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
            button,
        )
        time.sleep(1)

        # 确保按钮没有被遮挡
        driver.execute_script(
            """
            const btn = arguments[0];
            btn.style.outline = '3px solid red';
            """,
            button,
        )

        # 方法 1：Selenium 原生点击
        try:
            print("🚀 尝试 Selenium 原生 click()...")
            wait.until(EC.element_to_be_clickable(button))
            button.click()
        except Exception as e:
            print("⚠️ 原生 click() 失败，准备使用 ActionChains。")
            print("原生 click 错误：", repr(e))

            # 方法 2：真实鼠标移动点击
            try:
                print("🚀 尝试 ActionChains 点击...")
                ActionChains(driver).move_to_element(button).pause(0.3).click().perform()
            except Exception as e2:
                print("⚠️ ActionChains 点击失败，准备使用 JS MouseEvent。")
                print("ActionChains 错误：", repr(e2))

                # 方法 3：JS 派发完整鼠标事件
                print("🚀 尝试 JS MouseEvent 点击...")
                driver.execute_script(
                    """
                    const btn = arguments[0];

                    ['mouseover', 'mouseenter', 'mousemove', 'mousedown', 'mouseup', 'click'].forEach(type => {
                        const event = new MouseEvent(type, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            buttons: 1
                        });
                        btn.dispatchEvent(event);
                    });
                    """,
                    button,
                )

        print("⏳ 点击命令已发送，等待签到状态变化...")

        # 等待按钮状态变化
        try:
            wait.until(
                lambda d: is_checked_in(
                    d.find_element(By.CSS_SELECTOR, "button.checkin-button")
                )
            )
            fresh_button = driver.find_element(By.CSS_SELECTOR, "button.checkin-button")
            debug_button(fresh_button, "签到后按钮状态")
            print("✅ 签到成功！")
            return True
        except Exception:
            print("⚠️ 点击后按钮状态未变，尝试检查是否弹出了提示或页面异步较慢。")
            time.sleep(5)

            fresh_button = driver.find_element(By.CSS_SELECTOR, "button.checkin-button")
            debug_button(fresh_button, "延迟检查按钮状态")

            if is_checked_in(fresh_button):
                print("✅ 延迟检查后确认签到成功！")
                return True

            # 有些站点不改变按钮 class，但 title 或积分可能会变；这里保守提示
            print("❌ 签到按钮状态仍未变，可能点击没有触发签到请求。")
            driver.save_screenshot("checkin_state_not_changed.png")
            return False

    except Exception as e:
        print("❌ 签到流程异常：", repr(e))
        driver.save_screenshot("checkin_error.png")
        return False


def main():
    driver = build_driver()

    try:
        login(driver)

        button = find_checkin_button(driver)

        success = click_checkin_button(driver, button)

        if success:
            print("🎉 签到流程完成。")
            sys.exit(0)
        else:
            print("⚠️ 签到流程执行完成，但未能确认成功。")
            sys.exit(2)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
