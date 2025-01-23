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
    DISCORD_WEBHOOK_URL_1 = os.getenv("DISCORD_WEBHOOK_URL_1")
    if DISCORD_WEBHOOK_URL_1 is None:
        raise Exception("At least one DISCORD_WEBHOOK_URL is required. See docs or run 'source vars.sh' before the 'cli' command.")
    alert_bot_1 = Discord(url=DISCORD_WEBHOOK_URL_1)
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
        return (f"\n**DISPUTABLE VALUE**\n{new_report.link}\nCheck latest reports here: {fetch_dashboard['reporter_logs']}\n"
        f"Initiate a dispute on <12h old reports here: {fetch_dashboard['submit_dispute']}\n"
        f"Report: {new_report.asset}/{new_report.currency}: {new_report.value}")
    else:
        return (f"\n**NEW VALUE**\n{new_report.link}\nCheck latest reports here {fetch_dashboard['reporter_logs']}"
        f"Report: {new_report.asset}/{new_report.currency}: {new_report.value}")


def send_discord_msg(msg: str) -> None:
    """Send Discord alert."""
    MONITOR_NAME = os.getenv("MONITOR_NAME")
    message = f"❗{MONITOR_NAME} Found Something❗\n"
    get_alert_bot_1().post(content=message + msg)
    try:
        get_alert_bot_2().post(content=message + msg)
    except Exception as e:
        click.echo(f"alert bot 2 not used? {e}")
        pass
    try:
        get_alert_bot_3().post(content=message + msg)
    except Exception as e:
        click.echo(f"alert bot 3 not used? {e}")
        pass
    click.echo("Alerts sent!")
    return
