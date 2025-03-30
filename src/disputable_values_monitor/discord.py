"""Send text messages using Twilio."""
import os
from typing import Any
from dotenv import load_dotenv

load_dotenv()

import click
from discordwebhook import Discord

from disputable_values_monitor import ALWAYS_ALERT_QUERY_TYPES

from disputable_values_monitor.utils import get_logger
from disputable_values_monitor.utils import fetch_dashboard

logger = get_logger(__name__)


def generic_alert(msg: str) -> None:
    """Send a Discord message via webhook."""
    send_discord_msg(msg)
    return


def get_alert_bot_1() -> Discord:
    """Read the Discord webhook url from the environment."""
    discord_webhook_url_1 = os.getenv("DISCORD_WEBHOOK_URL_1")
    if discord_webhook_url_1 is None:
        logger.error(f"At least one DISCORD_WEBHOOK_URL is required. Check .env before running the 'cli' command.")
        raise Exception("At least one DISCORD_WEBHOOK_URL is required. Check .env before running the 'cli' command.")
    alert_bot_1 = Discord(url=discord_webhook_url_1)
    return alert_bot_1


def get_alert_bot_2() -> Discord:
        return Discord(url=os.getenv("DISCORD_WEBHOOK_URL_2"))


def get_alert_bot_3() -> Discord:
        return Discord(url=os.getenv("DISCORD_WEBHOOK_URL_3"))
    
def token_balance_alert(msg: str) -> None:
    """send an alert when FETCH or PLS are below the threshold"""
    send_discord_msg(msg)
    logger.info("Token balance alert sent")
    return


def dispute_alert(msg: str) -> None:
    """send an alert that the dispute was successful to the user"""
    send_discord_msg(msg)
    return


def alert(all_values: bool, new_report: Any) -> None:

    if new_report.query_type in ALWAYS_ALERT_QUERY_TYPES:
        msg = generate_alert_msg(False, new_report)
        send_discord_msg(msg)

        return

    # Account for unsupported queryIDs
    if new_report.disputable is not None:
        if new_report.disputable:
            msg = generate_alert_msg(True, new_report)

    # If user wants ALL NewReports
    if all_values:
        msg = generate_alert_msg(False, new_report)
        send_discord_msg(msg)
        

    else:
        if new_report.disputable:
            msg = generate_alert_msg(True, new_report)
            send_discord_msg(msg)


def generate_alert_msg(disputable: bool, new_report: str) -> str:
    """Generate an alert message string that
    includes a link to a relevant expolorer."""

    if disputable:
        return (f"**DISPUTABLE VALUE**\n\n{new_report.link}\nCheck latest reports here: {fetch_dashboard['reporter_logs']}\n"
        f"Initiate a dispute on <12h old reports here: {fetch_dashboard['submit_dispute']}\n\n"
        f"{new_report.disp_info}")
    else:
        return (f"\n**NEW VALUE**\n{new_report.link}\nCheck latest reports here {fetch_dashboard['reporter_logs']}"
        f"Report: {new_report.asset}/{new_report.currency}: {new_report.value}")


def send_discord_msg(msg: str) -> None:
    """Send Discord alert."""
    monitor_name = os.getenv("MONITOR_NAME")
    message = f"{monitor_name} Found Something:\n"
    get_alert_bot_1().post(content=message + msg)
    logger.info(f"Alert sent bot 1: {msg}")
    
    discord_webhook_url_2 = os.getenv("DISCORD_WEBHOOK_URL_2")
    if not discord_webhook_url_2:
        pass
    else:
        try:
            get_alert_bot_2().post(content=message + msg)
            logger.info(f"Alert sent bot 2: {msg}")
        except Exception as e:
            click.echo(f"alert bot 2 not used? {e}")
            logger.info(f"alert bot 2 not used? {e}")
        pass
    discord_webhook_url_3 = os.getenv("DISCORD_WEBHOOK_URL_3")
    if not discord_webhook_url_3:
        pass
    else:
        try:
            get_alert_bot_3().post(content=message + msg)
            logger.info(f"Alert sent bot 3: {msg}")
        except Exception as e:
            click.echo(f"alert bot 3 not used? {e}")
            logger.info(f"alert bot 3 not used? {e}")
        pass
    click.echo("Alert sent! dvmLog.txt for more info.")
    return
