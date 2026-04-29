import os
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


HOME_URL = "https://www.nodeloc.com/"

# 你提供的精确选择器 + 更稳的候选选择器
CHECKIN_SELECTORS = [
    "#ember3 > div.drop-down-mode.d-header-wrap > header > div > div > div.panel > ul > li.header-dropdown-toggle.checkin-icon > button",
    "li.header-dropdown-toggle.checkin-icon > button",
    "li.checkin-icon button",
    "button.checkin-button",
    ".checkin-icon button",
]


def debug_dump(page, name="debug"):
    """
    GitHub Actions 失败时保留截图和 HTML，方便你下载 artifact 后排查。
    """
    try:
        page.screenshot(path=f"{name}.png", full_page=True)
        with open(f"{name}.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print(f"🧩 已保存调试文件: {name}.png / {name}.html")
    except Exception as e:
        print(f"⚠️ 保存调试文件失败: {e}")


def wait_page_ready(page):
    """
    尽量等待前端渲染完成。
    """
    try:
        page.wait_for_load_state("domcontentloaded", timeout=30000)
    except Exception:
        pass

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        # 有些站点长连接会导致 networkidle 等不到，不影响继续执行
        pass

    time.sleep(2)


def is_logged_in(page):
    """
    NodeLoc/Discourse 登录后常见用户元素。
    """
    login_indicators = [
        ".current-user",
        "#current-user",
        "li.header-dropdown-toggle.current-user",
        "button[aria-label*='用户']",
        "button[aria-label*='user']",
        ".d-header-icons .current-user",
    ]

    for selector in login_indicators:
        try:
            if page.locator(selector).count() > 0:
                return True
        except Exception:
            continue

    return False


def login(page, username, password):
    print("正在访问 NodeLoc 首页...")
    page.goto(HOME_URL, timeout=60000, wait_until="domcontentloaded")
    wait_page_ready(page)

    if is_logged_in(page):
        print("✅ 当前已经是登录状态。")
        return True

    login_selectors = [
        ".login-button",
        "button.login-button",
        "button:has-text('登录')",
        "a:has-text('登录')",
        "button:has-text('Log In')",
        "a:has-text('Log In')",
    ]

    login_btn = None
    for selector in login_selectors:
        locator = page.locator(selector)
        if locator.count() > 0:
            login_btn = locator.first
            print(f"找到登录按钮: {selector}")
            break

    if not login_btn:
        print("❌ 未找到登录按钮。")
        debug_dump(page, "login_button_not_found")
        return False

    print("正在打开登录弹窗...")
    login_btn.click(timeout=15000)
    time.sleep(2)

    try:
        page.wait_for_selector("#login-account-name", timeout=15000)
        page.fill("#login-account-name", username)
        page.fill("#login-account-password", password)

        # 用真实点击，不用 JS click
        page.locator("#login-button").click(timeout=15000)

        # 登录后可能跳转/刷新，也可能只是弹窗关闭
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

        time.sleep(5)

        # 重新访问首页，确保 cookie 和登录态生效
        page.goto(HOME_URL, timeout=60000, wait_until="domcontentloaded")
        wait_page_ready(page)

        if is_logged_in(page):
            print("✅ 登录成功！")
            return True

        print("❌ 登录后没有检测到用户状态，可能有验证码、2FA 或账号密码错误。")
        debug_dump(page, "login_failed")
        return False

    except Exception as e:
        print(f"❌ 登录流程失败: {e}")
        debug_dump(page, "login_exception")
        return False


def find_checkin_button(page):
    """
    依次尝试多个选择器，并返回第一个可见按钮。
    """
    print("🔍 正在寻找签到按钮...")

    for selector in CHECKIN_SELECTORS:
        try:
            locator = page.locator(selector)
            count = locator.count()
            print(f"选择器: {selector}，匹配数量: {count}")

            if count == 0:
                continue

            for i in range(count):
                btn = locator.nth(i)
                try:
                    btn.wait_for(state="attached", timeout=5000)
                    if btn.is_visible(timeout=3000):
                        print(f"✅ 找到可见签到按钮: {selector}，index={i}")
                        return btn, selector
                except Exception:
                    continue

        except Exception as e:
            print(f"⚠️ 选择器检查失败: {selector}，原因: {e}")

    return None, None


def button_looks_checked_in(btn):
    """
    根据按钮状态、class、aria、title、文本判断是否已签到。
    """
    try:
        class_attr = btn.get_attribute("class") or ""
        disabled_attr = btn.get_attribute("disabled")
        aria_label = btn.get_attribute("aria-label") or ""
        title = btn.get_attribute("title") or ""
        text = btn.inner_text(timeout=3000) or ""

        merged = " ".join([class_attr, aria_label, title, text]).lower()

        checked_keywords = [
            "checked-in",
            "checked",
            "已签到",
            "今日已签到",
            "signed",
            "signed in",
            "checkined",
        ]

        if disabled_attr is not None:
            return True

        if btn.is_disabled():
            return True

        return any(keyword.lower() in merged for keyword in checked_keywords)

    except Exception:
        return False


def click_checkin(page, btn):
    """
    使用 Playwright 真实鼠标点击，并同时监听可能的签到请求。
    """
    print("👉 准备执行签到...")

    try:
        btn.scroll_into_view_if_needed(timeout=10000)
    except Exception:
        pass

    time.sleep(1)

    try:
        box = btn.bounding_box()
        print(f"按钮位置: {box}")
    except Exception:
        box = None

    if button_looks_checked_in(btn):
        print("🎉 检查结果: 今日已签到，无需重复操作。")
        return True

    # 先 hover，再真实点击
    try:
        btn.hover(timeout=10000)
        time.sleep(0.5)
    except Exception as e:
        print(f"⚠️ hover 失败，继续尝试点击: {e}")

    print("🚀 正在使用真实点击触发签到...")

    response_hit = None

    def watch_response(response):
        nonlocal response_hit
        url = response.url.lower()
        # 放宽匹配：只要 URL 里出现 checkin / check-in / daily / award / user_actions 等都记录
        keywords = [
            "checkin",
            "check-in",
            "daily",
            "award",
            "points",
            "user_actions",
            "plugin",
        ]
        if any(k in url for k in keywords):
            response_hit = response
            print(f"📡 捕获到疑似签到响应: {response.status} {response.url}")

    page.on("response", watch_response)

    clicked = False

    # 第一优先：Playwright 正常点击
    try:
        btn.click(timeout=15000)
        clicked = True
        print("✅ Playwright click 已执行。")
    except Exception as e:
        print(f"⚠️ 普通 click 失败: {e}")

    # 第二尝试：force click
    if not clicked:
        try:
            btn.click(timeout=15000, force=True)
            clicked = True
            print("✅ force click 已执行。")
        except Exception as e:
            print(f"⚠️ force click 失败: {e}")

    # 第三尝试：坐标点击
    if not clicked and box:
        try:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            time.sleep(0.2)
            page.mouse.down()
            time.sleep(0.1)
            page.mouse.up()
            clicked = True
            print("✅ 鼠标坐标点击已执行。")
        except Exception as e:
            print(f"⚠️ 坐标点击失败: {e}")

    if not clicked:
        print("❌ 所有点击方式都失败。")
        debug_dump(page, "checkin_click_failed")
        return False

    print("⏳ 等待签到请求和页面状态变化...")

    # 等网络和前端更新
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    time.sleep(5)

    # 重新获取按钮，避免前端重渲染后旧 locator 状态不准
    new_btn, selector = find_checkin_button(page)

    if new_btn and button_looks_checked_in(new_btn):
        print("🎉 签到成功！按钮状态已变为已签到。")
        return True

    # 有些签到不会改按钮，但请求成功
    if response_hit is not None and 200 <= response_hit.status < 300:
        print("🎉 签到请求已成功返回 2xx。若按钮未变化，可能是前端未刷新。")
        return True

    print("⚠️ 未能确认签到成功。将刷新页面后再检查一次。")

    try:
        page.reload(wait_until="domcontentloaded", timeout=60000)
        wait_page_ready(page)

        refreshed_btn, _ = find_checkin_button(page)
        if refreshed_btn and button_looks_checked_in(refreshed_btn):
            print("🎉 刷新后确认: 今日已签到。")
            return True

    except Exception as e:
        print(f"⚠️ 刷新复查失败: {e}")

    debug_dump(page, "checkin_not_confirmed")
    print("❌ 点击已执行，但没有确认到签到成功。请下载调试截图/HTML 检查按钮或接口变化。")
    return False


def auto_login_and_checkin():
    username = os.environ.get("NODELOC_USERNAME")
    password = os.environ.get("NODELOC_PASSWORD")

    if not username or not password:
        print("错误: 未找到账号或密码，请检查 GitHub Secrets 配置 NODELOC_USERNAME / NODELOC_PASSWORD。")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1920,1080",
            ],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )

        page = context.new_page()

        try:
            ok = login(page, username, password)
            if not ok:
                return

            print("🔄 重新进入首页，准备签到...")
            page.goto(HOME_URL, timeout=60000, wait_until="domcontentloaded")
            wait_page_ready(page)

            btn, selector = find_checkin_button(page)

            if not btn:
                print("❌ 找不到签到按钮。")
                debug_dump(page, "checkin_button_not_found")
                print("请根据下方步骤手动定位新的签到按钮选择器。")
                return

            print(f"使用签到按钮选择器: {selector}")
            click_checkin(page, btn)

        except Exception as e:
            print(f"执行过程中出现错误: {e}")
            debug_dump(page, "runtime_exception")
        finally:
            browser.close()


if __name__ == "__main__":
    auto_login_and_checkin()
