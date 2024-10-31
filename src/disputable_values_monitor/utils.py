"""Helper functions."""
import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from typing import Optional
from typing import Union

from dotenv import load_dotenv
load_dotenv()

import click
from chained_accounts import ChainedAccount
from chained_accounts import find_accounts
from telliot_core.apps.telliot_config import TelliotConfig
from telliot_feeds.utils.cfg import setup_account

from web3 import Web3
import asyncio

def get_tx_explorer_url(tx_hash: str, cfg: TelliotConfig) -> str:
    """Get transaction explorer URL."""
    explorer: str = cfg.get_endpoint().explorer
    if explorer is not None:
        return explorer + "/tx/" + tx_hash
    else:
        return f"Explorer not defined for chain_id {cfg.main.chain_id}"


@dataclass
class Topics:
    """Topics for Tellor events."""

    # sha3("NewReport(bytes32,uint256,uint256,uint256,uint256)")
    NEW_REPORT: str = "0x48e9e2c732ba278de6ac88a3a57a5c5ba13d3d8370e709b3b98333a57876ca95"  # oracle.NewReport
    # sha3("NewOracleAddress(address,uint256)")
    NEW_ORACLE_ADDRESS: str = (
        "0x31f30a38b53d085dbe09f68f490447e9032b29de8deb5aae4ccd3577a09ff284"  # oracle.NewOracleAddress
    )
    # sha3("NewProposedOracleAddress(address,uint256)")
    NEW_PROPOSED_ORACLE_ADDRESS: str = (
        "0x8fe6b09081e9ffdaf91e337aba6769019098771106b34b194f1781b7db1bf42b"  # oracle.NewProposedOracleAddress
    )


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
    fh = logging.FileHandler("dvmLog.txt")
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

def get_reporters():
    reporters = [reporter.strip() for reporter in os.getenv('REPORTERS', "").split(',')]
    return [Web3.toChecksumAddress(reporter) for reporter in reporters if reporter != ""]

def create_async_task(function, *args, **kwargs):
    return asyncio.create_task(function(*args, **kwargs))

#Fetch dashboard or other useful links to use in alerts etc according to chain id
NETWORK_ID = os.getenv('NETWORK_ID')

base_urls = {
    '943': f'https://testnet.fetchoracle.com/',
    '369': f'https://go.fetchoracle.com/'
}

chain_url = base_urls.get(NETWORK_ID, (f'No Dashboard for {NETWORK_ID} chain. Check tx link.'))

# Construct the links using f-strings
fetch_dashboard = {
    'home': f'{chain_url}',
    'vote': f'{chain_url}#/vote-on-dispute',
    'reporter_logs': f'{chain_url}#/reporter-logs',
    'submit_dispute': f'{chain_url}#/submit-dispute'
}
