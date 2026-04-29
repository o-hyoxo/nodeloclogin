import os
import time
from playwright.sync_api import sync_playwright

def auto_login_and_checkin():
    username = os.environ.get('NODELOC_USERNAME')
    password = os.environ.get('NODELOC_PASSWORD')

    if not username or not password:
        print("错误: 未找到账号或密码，请检查 GitHub Secrets 配置。")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled'] 
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()

        try:
            print("正在访问 NodeLoc 首页...")
            # 首页加载可以使用 domcontentloaded 加快速度
            page.goto('https://www.nodeloc.com/', timeout=60000, wait_until='domcontentloaded')
            time.sleep(3)

            # ================= 登录流程 =================
            login_btn = page.locator('.login-button')
            if login_btn.count() > 0:
                print("找到登录按钮，正在打开登录弹窗...")
                login_btn.first.click()
                time.sleep(2) 

                page.fill('#login-account-name', username)
                page.fill('#login-account-password', password)
                page.click('#login-button')
                time.sleep(6) 
            else:
                print("⚠️ 未找到首页的登录按钮，尝试直接检查是否已登录。")

            # ================= 关键修复 1：等待网络安静 =================
            print("🔄 刷新页面确保拿到登录后的 Cookie，并等待页面完全加载...")
            # 改为 networkidle，确保网站后端的 JS 代码完全加载并绑定到按钮上
            page.goto('https://www.nodeloc.com/', timeout=60000, wait_until='networkidle') 
            time.sleep(2) 
            
            # ================= 签到流程 =================
            if page.locator('.current-user').count() > 0 or page.locator('#current-user').count() > 0:
                print("✅ 登录成功！")
                
                print("🔍 正在寻找签到按钮...")
                checkin_selector = "li.header-dropdown-toggle.checkin-icon button.checkin-button"
                checkin_btn = page.locator(checkin_selector)
                
                if checkin_btn.count() > 0:
                    btn = checkin_btn.first
                    
                    class_attr = btn.get_attribute("class") or ""
                    is_disabled = btn.is_disabled()
                    
                    if "checked-in" in class_attr or is_disabled:
                        print("🎉 检查结果: 今日已签到，无需重复操作。")
                    else:
                        print("👉 尝试执行签到...")
                        btn.hover()
                        time.sleep(1)
                        
                        # ================= 关键修复 2：使用真实的模拟点击 =================
                        # 放弃 JS evaluate，使用 Playwright 原生点击，force=True 可以穿透一些透明遮罩层
                        btn.click(force=True)
                        print("🚀 原生点击命令已发送，正在等待服务器响应...")
                        
                        # ================= 关键修复 3：智能等待状态改变 =================
                        try:
                            # 相比于死等 time.sleep(4)，让程序智能盯住按钮，只要按钮多出了 'checked-in' 这个类名，就说明签到成功了
                            page.wait_for_selector("li.header-dropdown-toggle.checkin-icon button.checkin-button.checked-in", timeout=10000)
                            print("🎉 签到大成功！(按钮状态已变为已签到)")
                        except Exception:
                            print("⚠️ 点击已执行，但10秒内按钮状态未变。可能是被论坛安全策略拦截，或网络存在延迟。")
                else:
                    print("❌ 找不到签到按钮，请检查论坛是否更换了前端主题或结构。")
            else:
                print("❌ 登录失败，请检查账号密码或验证码拦截。")

        except Exception as e:
            print(f"执行过程中出现错误: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    auto_login_and_checkin()
