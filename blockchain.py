import os
import sys
import json
import hashlib
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

SEPOLIA_CHAIN_ID = 11155111


def canonical_hash(verification_data: dict) -> str:
    canonical = json.dumps(verification_data, sort_keys=True, separators=(",", ":"))
    return "0x" + hashlib.sha256(canonical.encode()).hexdigest()


def _get_web3():
    from web3 import Web3

    rpc_url = os.getenv("SEPOLIA_RPC_URL", "")
    if not rpc_url:
        raise ValueError(
            "SEPOLIA_RPC_URL not set. Get one from https://alchemy.com (free tier works).\n"
            "Add to .env: SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/YOUR_KEY"
        )
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"Cannot connect to {rpc_url}")
    return w3


def _get_account(w3):
    """Load the signing account from env."""
    from eth_account import Account

    private_key = os.getenv("PRIVATE_KEY", "")
    if not private_key:
        raise ValueError(
            "PRIVATE_KEY not set. Export your Sepolia wallet private key.\n"
            "Add to .env: PRIVATE_KEY=0x..."
        )
    return Account.from_key(private_key)


def _build_fee_fields(w3):
    try:
        latest = w3.eth.get_block("latest")
        base_fee = latest.get("baseFeePerGas")
        if base_fee:
            priority = w3.to_wei(1.5, "gwei")
            return {"maxFeePerGas": int(base_fee * 2 + priority), "maxPriorityFeePerGas": int(priority)}
    except Exception:
        pass
    return {"gasPrice": w3.eth.gas_price}


def write_genesis_record(w3=None) -> str:
    if w3 is None:
        w3 = _get_web3()

    account = _get_account(w3)

    print("  [blockchain] Using raw data-embedding mode (no contract deployment needed)")

    data_hash = hashlib.sha256(
        f"face-verifier-genesis-{int(time.time())}".encode()
    ).digest()

    nonce = w3.eth.get_transaction_count(account.address)

    tx = {
        "from": account.address,
        "to": account.address,
        "value": 0,
        "nonce": nonce,
        "gas": 22000,
        "chainId": SEPOLIA_CHAIN_ID,
        "data": "0x" + data_hash.hex(),
    }
    tx.update(_build_fee_fields(w3))

    signed_tx = w3.eth.account.sign_transaction(tx, account.key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300, poll_latency=5)

    print(f"  [blockchain] Genesis tx: 0x{tx_hash.hex()}")
    print(f"  [blockchain] Block: {receipt['blockNumber']}")

    return tx_hash.hex()


def deploy_contract(w3=None) -> str:
    return write_genesis_record(w3)


def record_verification(face_encoding_hash: str, match_url: str, platform: str, title: str = "", source: str = "", w3=None) -> dict:

    if w3 is None:
        w3 = _get_web3()

    account = _get_account(w3)

    verification_data = {
        "face_hash": face_encoding_hash,
        "post_url": match_url,
        "platform": platform,
        "title": title or "",
        "source": source or "",
        "timestamp": int(time.time()),
    }

    data_hex = canonical_hash(verification_data)
    data_bytes = bytes.fromhex(data_hex[2:])

    prefix = b"FACEVERIFY:"
    payload = prefix + data_bytes
    payload_hex = "0x" + payload.hex()

    nonce = w3.eth.get_transaction_count(account.address)

    tx = {
        "from": account.address,
        "to": account.address,
        "value": 0,
        "nonce": nonce,
        "gas": 26000,
        "chainId": SEPOLIA_CHAIN_ID,
        "data": payload_hex,
    }
    tx.update(_build_fee_fields(w3))

    signed_tx = w3.eth.account.sign_transaction(tx, account.key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"  TX submitted: 0x{tx_hash.hex()}")
    print("  Waiting for confirmation...")

    try:
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300, poll_latency=5)
    except Exception as e:
        print(f"  Transaction still pending: 0x{tx_hash.hex()} ({e})")
        return {
            "tx_hash": tx_hash.hex(),
            "pending": True,
            "status": "pending",
            "etherscan_url": f"https://sepolia.etherscan.io/tx/{tx_hash.hex()}",
            "verification_data": verification_data,
            "on_chain_data_hash": data_hex,
            "network": "ethereum-sepolia",
            "chain_id": SEPOLIA_CHAIN_ID,
            "verifier_address": account.address,
        }

    etherscan_url = f"https://sepolia.etherscan.io/tx/{tx_hash.hex()}"

    result = {
        "tx_hash": tx_hash.hex(),
        "block_number": receipt["blockNumber"],
        "gas_used": receipt["gasUsed"],
        "status": "success" if receipt.get("status") == 1 else "failed",
        "etherscan_url": etherscan_url,
        "verification_data": verification_data,
        "on_chain_data_hash": data_hex,
        "network": "ethereum-sepolia",
        "chain_id": SEPOLIA_CHAIN_ID,
        "verifier_address": account.address,
    }

    print(f"  [blockchain] TX: 0x{tx_hash.hex()}")
    print(f"  [blockchain] Block: {receipt['blockNumber']}")
    print(f"  [blockchain] Gas: {receipt['gasUsed']}")
    print(f"  [blockchain] Etherscan: {etherscan_url}")

    return result


def verify_on_chain(tx_hash: str, w3=None) -> dict:
    if w3 is None:
        w3 = _get_web3()

    tx = w3.eth.get_transaction(tx_hash)
    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
    except Exception:
        receipt = None

    data = tx["input"]
    if isinstance(data, bytes):
        data = "0x" + data.hex()

    if data.startswith("0x") and len(data) > 2:
        raw = bytes.fromhex(data[2:])
        if raw.startswith(b"FACEVERIFY:"):
            payload = raw[len(b"FACEVERIFY:"):]
            return {
                "found": True,
                "data_hash": "0x" + payload.hex(),
                "block_number": receipt["blockNumber"] if receipt else None,
                "from": tx["from"],
                "to": tx["to"],
                "status": "success" if receipt and receipt.get("status") == 1 else ("pending" if receipt is None else "failed"),
                "network": "ethereum-sepolia",
                "etherscan_url": f"https://sepolia.etherscan.io/tx/{tx_hash}",
            }

    return {"found": False, "error": "Transaction data does not match FACEVERIFY format"}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python blockchain.py deploy          – deploy genesis tx")
        print("  python blockchain.py record <face_hash> <url> <platform>")
        print("  python blockchain.py verify <tx_hash>")
        sys.exit(1)

    action = sys.argv[1]

    if action == "deploy":
        tx = deploy_contract()
        print(json.dumps({"genesis_tx": tx}, indent=2))

    elif action == "record":
        if len(sys.argv) < 5:
            print("Usage: python blockchain.py record <face_hash> <url> <platform>")
            sys.exit(1)
        result = record_verification(sys.argv[2], sys.argv[3], sys.argv[4])
        print(json.dumps(result, indent=2))

    elif action == "verify":
        if len(sys.argv) < 3:
            print("Usage: python blockchain.py verify <tx_hash>")
            sys.exit(1)
        result = verify_on_chain(sys.argv[2])
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown action: {action}")
        sys.exit(1)
