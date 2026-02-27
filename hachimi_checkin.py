import os
import time
import re
import platform
import requests
from typing import Optional

from seleniumbase import SB
from pyvirtualdisplay import Display

LOGIN_URL = "https://mambo-hachimi.biliblili.uk/login"
DASHBOARD_KEYWORD = "仪表盘"
CHECKIN_TEXT = "立即签到"


# =========================
# Xvfb
# =========================
def setup_xvfb():
    if platform.system().lower() == "linux" and not os.environ.get("DISPLAY"):
        display = Display(visible=False, size=(1920, 1080))
        display.start()
        os.environ["DISPLAY"] = display.new_display_var
        print("🖥️ Xvfb 已启动")
        return display
    return None


# =========================
# 工具函数
# =========================
def mask_account(name: str) -> str:
    if len(name) <= 6:
        return name[0] + "***" + name[-1]
    return f"{name[:3]}***{name[-3:]}"


def extract_number(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"(\d+(\.\d+)?)", text.replace(",", ""))
    return float(m.group(1)) if m else None


def tg_send(token: str, chat_id: str, msg: str):
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
    except Exception as e:
        print(f"⚠️ TG 通知失败: {e}")


# =========================
# 账号加载
# =========================
def load_accounts():
    raw = (os.getenv("HACHIMI_BATCH") or "").strip()
    if not raw:
        raise RuntimeError("❌ 缺少 HACHIMI_BATCH")

    accounts = []

    for idx, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = [x.strip() for x in line.split(",")]

        if len(parts) == 2:
            username, password = parts
            tg_token = ""
            tg_chat_id = ""
        elif len(parts) == 4:
            username, password, tg_token, tg_chat_id = parts
        else:
            raise RuntimeError(
                f"❌ HACHIMI_BATCH 第 {idx} 行格式错误（应为 2 或 4 列）"
            )

        accounts.append((username, password, tg_token, tg_chat_id))

    return accounts


# =========================
# 奖励提取（核心）
# =========================
def get_checkin_reward(sb: SB) -> Optional[float]:
    """
    从签到成功卡片中提取奖励金额
    """
    try:
        sb.wait_for_text("签到成功！", timeout=15)

        reward_text = sb.get_text(
            "//p[contains(@class,'text-yellow-300')]//span"
        )

        return extract_number(reward_text)

    except Exception as e:
        print("⚠️ 奖励解析失败:", e)
        return None


# =========================
# 单账号流程
# =========================
def checkin_one(username: str, password: str):
    with SB(uc=True, locale="zh", test=True) as sb:

        sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=5)
        sb.wait_for_element_visible("form", timeout=30)

        # 输入账号密码
        sb.type("form input[type='text']", username)
        sb.type("form input[type='password']", password)
        sb.click("button[type='submit']")

        # === CF 人机验证（多次尝试） ===
        for _ in range(3):
            try:
                sb.uc_gui_click_captcha()
                time.sleep(5)
            except Exception:
                pass

            # 已进入仪表盘
            if sb.is_text_visible(DASHBOARD_KEYWORD):
                break

            # 仍在登录页，继续等
            if sb.is_text_visible("使用您的账号登录"):
                time.sleep(3)
                continue

        # === 最终判断 ===
        if not sb.is_text_visible(DASHBOARD_KEYWORD):
            return False, {
                "status": "login_failed",
                "reward": None,
            }

        masked = mask_account(username)
        print(f"👤 登录成功：{masked}")

        # ===== 已签到判断 =====
        if sb.is_text_visible("今日签到已完成") or sb.is_text_visible("签到成功！"):
            reward = get_checkin_reward(sb)
            return True, {
                "status": "already",
                "reward": reward,
            }

        # ===== 执行签到 =====
        sb.wait_for_element_visible(
            f"button:contains('{CHECKIN_TEXT}')", timeout=30
        )
        sb.click(f"button:contains('{CHECKIN_TEXT}')")

        time.sleep(2)

        try:
            sb.uc_gui_click_captcha()
            time.sleep(3)
        except Exception:
            pass

        reward = get_checkin_reward(sb)

        return True, {
            "status": "checked",
            "reward": reward,
        }


# =========================
# 主入口
# =========================
def main():
    display = setup_xvfb()
    accounts = load_accounts()

    try:
        for i, (u, p, tg_token, tg_chat_id) in enumerate(accounts, start=1):
            masked = mask_account(u)

            print("\n" + "=" * 60)
            print(f"🔐 [{i}/{len(accounts)}] {masked}")
            print("=" * 60)

            try:
                ok, data = checkin_one(u, p)

                if not ok:
                    msg = f"❌ *hachimi 登录失败*\n账号: `{masked}`"

                else:
                    reward_display = (
                        f"+{data['reward']}"
                        if data["reward"] is not None
                        else "未知"
                    )

                    if data["status"] == "already":
                        msg = (
                            f"☑️ *hachimi 今日已签到*\n"
                            f"账号: `{masked}`\n"
                            f"奖励: `{reward_display}`"
                        )
                    else:
                        msg = (
                            f"✅ *hachimi 签到成功*\n"
                            f"账号: `{masked}`\n"
                            f"奖励: `{reward_display}`"
                        )

            except Exception as e:
                msg = f"💥 *hachimi 异常*\n账号: `{masked}`\n错误: `{e}`"

            print(msg)
            tg_send(tg_token, tg_chat_id, msg)

            time.sleep(3)

    finally:
        if display:
            display.stop()


if __name__ == "__main__":
    main()