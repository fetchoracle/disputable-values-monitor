"""Helper functions."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from typing import Optional
from typing import Union
from typing import TypedDict

import asyncio
from web3 import Web3

import click
from chained_accounts import ChainedAccount
from chained_accounts import find_accounts
from telliot_core.apps.telliot_config import TelliotConfig
from telliot_core.model.endpoints import RPCEndpoint
from telliot_feeds.utils.cfg import setup_account
from fetch_disputables.handle_connect_endpoint import get_endpoint

from dotenv import load_dotenv
load_dotenv()

def get_tx_explorer_url(tx_hash: str, cfg: TelliotConfig) -> str:
    """Get transaction explorer URL."""
    explorer: str = get_endpoint(cfg, cfg.main.chain_id).explorer
    if explorer is not None and explorer[-1] != "/": explorer += "/"
    if explorer is not None:
        return explorer + "tx/" + tx_hash
    else:
        return f"Explorer not defined for chain_id {cfg.main.chain_id}"


@dataclass
class Topics:
    """Topics for Fetch events."""

    # Keccak256("NewReport(bytes32,uint256,bytes,uint256,bytes,address)")
    NEW_REPORT: str = "0x48e9e2c732ba278de6ac88a3a57a5c5ba13d3d8370e709b3b98333a57876ca95"  # oracle.NewReport
    # sha3("NewOracleAddress(address,uint256)")
    NEW_ORACLE_ADDRESS: str = (
        "0x31f30a38b53d085dbe09f68f490447e9032b29de8deb5aae4ccd3577a09ff284"  # oracle.NewOracleAddress
    )
    # sha3("NewProposedOracleAddress(address,uint256)")
    NEW_PROPOSED_ORACLE_ADDRESS: str = (
        "0x8fe6b09081e9ffdaf91e337aba6769019098771106b34b194f1781b7db1bf42b"  # oracle.NewProposedOracleAddress
    )
    # Keccak256("NewDispute(uint256,bytes32,uint256,address,address,uint256,uint256,uint256,uint256)")
    NEW_DISPUTE: str = "0xfbfeca72a80efb0d1aabf7f937aaec719fa5c81548a4ade65b40ecdec0afca4e"


@dataclass
class NewDispute:
    """NewDispute event."""

    tx_hash: str = ""
    timestamp: int = 0
    reporter: str = ""
    query_id: str = ""
    dispute_id: int = 0
    initiator: str = ""
    chain_id: int = 0
    link: str = ""
    blockNumber: int = 0
    startDate: int = 0
    voteRound: int = 0
    fee: int = 0
    voteRoundLength: int = 0


class MonitoredFeedInfo(TypedDict):
    datafeed_querytag: str
    datafeed_source: object
    trusted_value: float
    percentage_change: float
    threshold_amount: float
    threshold_metric: str

@dataclass
class NewReport:
    """NewReport event."""

    tx_hash: str = ""
    submission_timestamp: int = 0  # timestamp attached to NewReport event (NOT the time retrieved by the DVM)
    chain_id: int = 0
    link: str = ""
    query_type: str = ""
    value: Union[str, bytes, float, int] = 0
    asset: str = ""
    currency: str = ""
    query_id: str = ""
    disputable: Optional[bool] = None
    status_str: str = ""
    reporter: str = ""
    contract_address: str = ""
    removable: Optional[bool] = False
    blockNumber: int = 0
    monitored_feed: MonitoredFeedInfo = field(default_factory=dict)
    is_managed_feed: bool = False


def disputable_str(disputable: Optional[bool], query_id: str) -> str:
    """Return a string indicating whether the query is disputable."""
    if disputable is not None:
        return "yes ❗📲" if disputable else "no ✔️"
    return f"❗unsupported query ID: {query_id}"


def clear_console() -> None:
    """Clear the console."""
    # windows
    if os.name == "nt":
        _ = os.system("cls")
    # mac, linux (name=="posix")
    else:
        _ = os.system("clear")


def select_account(cfg: TelliotConfig, account: Optional[str]) -> Optional[ChainedAccount]:
    """Select an account for disputing, allow no account to be chosen."""

    if account is not None:
        accounts = find_accounts(name=account)
        click.echo(f"Your account name: {accounts[0].name if accounts else None}")
    else:
        run_alerts_only = click.confirm("Missing an account to send disputes. Run alerts only?")
        if not run_alerts_only:
            new_account = setup_account(cfg.main.chain_id)
            if new_account is not None:
                click.echo(f"{new_account.name} selected!")
                new_account.unlock()
                return new_account
            return None
        else:
            return None

    accounts[0].unlock()
    return accounts[0]


def get_logger(name: str) -> logging.Logger:
    """DVM logger

    Returns a logger that logs to file. The name arg
    should be the current file name. For example:
    _ = get_logger(name=__name__)
    """
    log_format = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    fh = RotatingFileHandler("log.txt", maxBytes=10000000)
    formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(formatter)
    logger = logging.getLogger(name)
    logger.addHandler(fh)
    logger.setLevel(logging.DEBUG)
    return logger


def are_all_attributes_none(obj: object) -> bool:
    """Check if all attributes of an object are None."""
    if not hasattr(obj, "__dict__"):
        return False
    for attr in obj.__dict__:
        if getattr(obj, attr) is not None:
            return False
    return True


def format_values(val: Any) -> Any:
    """shorten values for cli display"""
    if isinstance(val, float):
        return Decimal(f"{val:.4f}")
    elif len(str(val)) > 10:
        return f"{str(val)[:6]}...{str(val)[-5:]}"
    else:
        return val

def get_service_notification():
    return [service.lower().strip() for service in os.getenv('NOTIFICATION_SERVICE', "").split(',')]

def get_reporters():
    reporters = [reporter.strip() for reporter in os.getenv('REPORTERS', "").split(',')]
    return [Web3.toChecksumAddress(reporter) for reporter in reporters if reporter != ""]

def get_report_intervals():
    report_intervals = [int(interval) for interval in os.getenv('REPORT_INTERVALS', "").split(',') if interval != ""] 
    reporters_length = len(get_reporters())
    if len(report_intervals) != reporters_length:
        safe_default_time = 30 * 60
        log_msg = f"REPORT_INTERVALS for REPORTERS not properly configured, defaulting to {safe_default_time // 60} minutes for each reporter"
        print(log_msg)
        get_logger(__name__).warning(log_msg)
        return [30 * 60 for _ in range(reporters_length)]
    return report_intervals

def get_env_reporters_balance_threshold(env_variable_name: str):
    reporters_threshold = [int(interval) for interval in os.getenv(env_variable_name, "").split(',') if interval != ""]
 
    reporters_length = len(get_reporters())
    if len(reporters_threshold) != reporters_length:
        asset = 'FETCH' if env_variable_name == 'REPORTERS_FETCH_BALANCE_THRESHOLD' else 'PLS'
        safe_default_threshold = 200
        log_msg = f"{env_variable_name} for REPORTERS not properly configured, defaulting to {safe_default_threshold} {asset} for each reporter"
        print(log_msg)
        get_logger(__name__).warning(log_msg)
        return [safe_default_threshold for _ in range(reporters_length)]
    return reporters_threshold

def get_report_time_margin():
    return int(os.getenv('REPORT_TIME_MARGIN', 60 * 1))

def create_async_task(function, *args, **kwargs):
    return asyncio.create_task(function(*args, **kwargs))

def format_new_dispute_message(new_dispute: NewDispute):
    return (
        f"- Dispute Tx link: {new_dispute.link}\n"
        f"- Dispute ID: {new_dispute.dispute_id}\n"
        f"- Query ID: {new_dispute.query_id}\n"
        f"- Timestamp: {new_dispute.timestamp}\n"
        f"- Reporter: {new_dispute.reporter}\n"
        f"- Initiator: {new_dispute.initiator}\n"
        f"- Start date: {new_dispute.startDate}\n"
        f"- Vote round: {new_dispute.voteRound}\n"
        f"- Fee: {new_dispute.fee}\n"
        f"- Vote round length: {new_dispute.voteRoundLength}\n"
        f"- Chain ID: {new_dispute.chain_id}\n"
        f"- Block Number: {new_dispute.blockNumber}"
    )

def format_new_report_message(new_report: NewReport):
    return (
        f"- Tx link: {new_report.link}\n"
        f"- Query type: {new_report.query_type}\n"
        f"- Query ID: {new_report.query_id}\n"
        f"- Timestamp: {new_report.submission_timestamp}\n"
        f"- Reporter: {new_report.reporter}\n"
        f"- Contract Address: {new_report.contract_address}\n"
        f"- Asset: {new_report.asset}\n"
        f"- Currency: {new_report.currency}\n"
        f"- Value: {new_report.value}\n"
        f"- Disputable: {new_report.disputable}\n"
        f"- Chain ID: {new_report.chain_id}\n"
        f"- Removable: {new_report.removable}\n"
        f"- Block Number: {new_report.blockNumber}\n"
        f"- Monitored Feed:\n"
        f"  - Datafeed Querytag: {new_report.monitored_feed['datafeed_querytag']}\n"
        f"  - Datafeed Source: {new_report.monitored_feed['datafeed_source']}\n"
        f"  - Trusted Value: {new_report.monitored_feed['trusted_value']}\n"
        f"  - Percentage Change: {new_report.monitored_feed['percentage_change']}\n"
        f"  - Threshold Amount: {new_report.monitored_feed['threshold_amount']}\n"
        f"  - Threshold Metric: {new_report.monitored_feed['threshold_metric']}\n"
    )

class NotificationSources:
    NEW_DISPUTE_AGAINST_REPORTER = "New Dispute against Reporter"
    NEW_REPORT = "New Report"
    AUTO_DISPUTER_BEGAN_A_DISPUTE = "Auto-Disputer began a dispute"
    REPORTER_STOP_REPORTING = "Reporter stop reporting"
    ALL_REPORTERS_STOP_REPORTING = "All Reporters stop reporting"
    REPORTER_BALANCE_THRESHOLD = "Reporter balance threshold"
    DISPUTER_BALANCE_THRESHOLD = "Disputer balance threshold"
    REMOVE_REPORT = "Remove Report"
    TRANSACTION_REVERTED = "Transaction Reverted"

class EnvironmentAlerts:
    CRITICAL_DEFAULT = '["DISPUTE_AGAINST_REPORTER", "ALL_REPORTERS_STOP"]'
    HIGH_DEFAULT = '["DISPUTE_AGAINST_REPORTER", "BEGAN_DISPUTE", "REMOVE_REPORT", "ALL_REPORTERS_STOP"]'
    MID_DEFAULT = '["DISPUTABLE_REPORT", "REPORTER_STOP"]'
    LOW_DEFAULT = '["REPORTER_BALANCE", "DISPUTER_BALANCE"]'

    @staticmethod
    def get_all_alerts() -> list[str]:
        high = EnvironmentAlerts.get_high_alerts()
        mid = EnvironmentAlerts.get_mid_alerts()
        low = EnvironmentAlerts.get_low_alerts()
        return high + mid + low
    
    @staticmethod
    def get_critical_alerts() -> list[str]:
        return json.loads(os.getenv('CRITICAL_ALERTS', EnvironmentAlerts.CRITICAL_DEFAULT))
    
    @staticmethod
    def get_high_alerts() -> list[str]:
        return json.loads(os.getenv('HIGH_ALERTS', EnvironmentAlerts.HIGH_DEFAULT))
    
    @staticmethod
    def get_mid_alerts() -> list[str]:
        return json.loads(os.getenv('MID_ALERTS', EnvironmentAlerts.MID_DEFAULT))
    
    @staticmethod
    def get_low_alerts() -> list[str]:
        return json.loads(os.getenv('LOW_ALERTS', EnvironmentAlerts.LOW_DEFAULT))
    