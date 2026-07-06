"""Email service using shared notification SMTP settings and WordPress mail API."""
import os
import smtplib
import warnings
from datetime import datetime
from email.mime.text import MIMEText
from typing import Optional

import httpx
import urllib3
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.system_config import get_notification_config_values

# 禁用 SSL 警告（内部 Docker 网络中使用 HTTP/禁用验证）
warnings.filterwarnings("ignore", message="Unverified HTTPS request")
warnings.filterwarnings("ignore", category=DeprecationWarning)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# WordPress API endpoint - 可通过环境变量配置
WORDPRESS_BASE_URL = os.getenv("WORDPRESS_URL", "http://wordpress")
WORDPRESS_MAIL_API = f"{WORDPRESS_BASE_URL}/wp-json/flood-monitor/v1/send-mail"
WORDPRESS_TEST_API = f"{WORDPRESS_BASE_URL}/wp-json/flood-monitor/v1/test-mail"
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "").strip()

# 创建 httpx 客户端配置 - 在 Docker 内部网络中禁用 SSL 验证
HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def get_http_client():
    """Get configured HTTP client."""
    # 在 Docker 内部网络中使用 HTTP，不需要 SSL 验证
    return httpx.AsyncClient(
        timeout=HTTPX_TIMEOUT,
        verify=False,  # 禁用 SSL 验证（内部网络）
        http2=False    # 禁用 HTTP/2 避免兼容性问题
    )


async def send_email_via_wordpress(
    to: str,
    subject: str,
    message: str,
    headers: Optional[list] = None
) -> tuple[bool, str]:
    """Send email via WordPress API.
    
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        async with get_http_client() as client:
            payload = {
                "to": to,
                "subject": subject,
                "message": message
            }
            if headers:
                payload["headers"] = headers
            
            response = await client.post(
                WORDPRESS_MAIL_API,
                json=payload,
                headers={"X-Internal-Token": INTERNAL_API_TOKEN} if INTERNAL_API_TOKEN else None,
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("success", False), result.get("message", "未知状态")
            else:
                return False, f"WordPress API 错误: HTTP {response.status_code}"
    except httpx.ConnectError as e:
        return False, f"无法连接到 WordPress 服务 ({WORDPRESS_BASE_URL}): {str(e)}"
    except httpx.TimeoutException:
        return False, "WordPress 邮件服务超时"
    except Exception as e:
        return False, f"邮件发送异常: {str(e)}"


async def send_test_email_via_wordpress(to: str) -> tuple[bool, str]:
    """Send test email via WordPress API.
    
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        async with get_http_client() as client:
            response = await client.post(
                WORDPRESS_TEST_API,
                json={"to": to},
                headers={"X-Internal-Token": INTERNAL_API_TOKEN} if INTERNAL_API_TOKEN else None,
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("success", False), result.get("message", "测试邮件已发送")
            else:
                return False, f"WordPress API 错误: HTTP {response.status_code}"
    except httpx.ConnectError as e:
        return False, f"无法连接到 WordPress 服务 ({WORDPRESS_BASE_URL}): {str(e)}"
    except httpx.TimeoutException:
        return False, "WordPress 邮件服务超时"
    except Exception as e:
        return False, f"邮件发送异常: {str(e)}"


async def send_email_via_smtp(
    control_db: AsyncSession,
    to: str,
    subject: str,
    message: str,
) -> tuple[bool, str]:
    """Send email directly with SMTP settings stored in system config."""
    notify_config = await get_notification_config_values(control_db)

    if not notify_config["smtp_host"] or not notify_config["smtp_user"] or not notify_config["smtp_password"]:
        return False, "系统设置中的 SMTP 发信邮箱尚未完整配置"

    msg = MIMEText(message, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = notify_config["smtp_user"]
    msg["To"] = to

    try:
        if notify_config["smtp_port"] == 465:
            server = smtplib.SMTP_SSL(notify_config["smtp_host"], notify_config["smtp_port"], timeout=20)
        else:
            server = smtplib.SMTP(notify_config["smtp_host"], notify_config["smtp_port"], timeout=20)
            if notify_config["smtp_ssl"]:
                server.starttls()

        server.login(notify_config["smtp_user"], notify_config["smtp_password"])
        server.sendmail(notify_config["smtp_user"], [to], msg.as_string())
        server.quit()
        return True, "邮件已通过 SMTP 发送"
    except Exception as exc:
        return False, f"SMTP 发送失败: {exc}"


async def send_platform_email(
    control_db: AsyncSession,
    to: str,
    subject: str,
    message: str,
) -> tuple[bool, str]:
    """Send platform email using notification settings configured in system settings."""
    smtp_success, smtp_message = await send_email_via_smtp(control_db, to, subject, message)
    if smtp_success:
        return smtp_success, smtp_message

    notify_config = await get_notification_config_values(control_db)
    if not notify_config["email_enabled"]:
        return False, smtp_message

    wp_success, wp_message = await send_email_via_wordpress(to=to, subject=subject, message=message)
    if wp_success:
        return wp_success, wp_message

    return False, f"{smtp_message}; WordPress 发送失败: {wp_message}"


async def send_alert_email(
    control_db: AsyncSession,
    alert_type: str,
    severity: str,
    sensor_name: str,
    location: str,
    message: str,
    to_email: Optional[str] = None
) -> tuple[bool, str]:
    """Send alert notification email.
    
    Args:
        control_db: Control-plane database session
        alert_type: Type of alert (e.g., 'flood', 'offline')
        severity: Alert severity (e.g., 'critical', 'warning')
        sensor_name: Name of the sensor
        location: Location of the sensor
        message: Alert message
        to_email: Override recipient email (optional)
    
    Returns:
        tuple: (success: bool, message: str)
    """
    # Get notification config
    config = await get_notification_config_values(control_db)
    
    # Check if email notifications are enabled
    if not config["email_enabled"]:
        return False, "邮件通知未启用"
    
    # Determine recipient
    recipient = to_email or config["smtp_user"]
    if not recipient:
        return False, "未配置收件人邮箱"
    
    # Build email subject
    severity_map = {
        "critical": "紧急",
        "high": "警告",
        "medium": "提醒",
        "low": "通知",
    }
    severity_label = severity_map.get(severity, severity)
    
    alert_type_map = {
        "high_water": "水位告警",
        "forecast_high_water": "预报水位告警",
        "water_detected": "浸水告警",
        "sensor_offline": "设备离线",
        "low_battery": "电量告警",
    }
    alert_label = alert_type_map.get(alert_type, alert_type)
    
    subject = f"{severity_label} [{alert_label}] {sensor_name}"
    
    # Build email message
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    email_body = f"""水浸监测系统告警通知

═══════════════════════════════
告警信息
═══════════════════════════════
告警类型: {alert_label}
告警级别: {severity_label}
发生时间: {current_time}

═══════════════════════════════
设备信息
═══════════════════════════════
设备名称: {sensor_name}
安装位置: {location}

═══════════════════════════════
告警详情
═══════════════════════════════
{message}

═══════════════════════════════
此邮件由水浸监测系统自动发送
═══════════════════════════════
"""
    
    return await send_platform_email(
        control_db=control_db,
        to=recipient,
        subject=subject,
        message=email_body,
    )
