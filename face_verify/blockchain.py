import os
import sys
import json
import hashlib
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

CONTRACT_ABI = [
    {
        "inputs": [
            {"name": "_faceHash", "type": "bytes32"},
            {"name": "_matchUrl", "type": "string"},
            {"name": "_platform", "type": "string"},
        ],
        "name": "recordVerification",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "_index", "type": "uint256"}],
        "name": "getVerification",
        "outputs": [
            {"name": "faceHash", "type": "bytes32"},
            {"name": "matchUrl", "type": "string"},
            {"name": "platform", "type": "string"},
            {"name": "timestamp", "type": "uint256"},
            {"name": "verifier", "type": "address"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "verificationCount",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

CONTRACT_BYTECODE = None

SEPOLIA_CHAIN_ID = 11155111


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


def deploy_contract(w3=None) -> str:
    if w3 is None:
        w3 = _get_web3()

    account = _get_account(w3)

    print("  [blockchain] Using raw data-embedding mode (no contract deployment needed)")

    data_hash = hashlib.sha256(
        f"face-verifier-genesis-{int(time.time())}".encode()
    ).digest()

    nonce = w3.eth.get_transaction_count(account.address)
    gas_price = w3.eth.gas_price

    tx = {
        "from": account.address,
        "to": account.address,
        "value": 0,
        "nonce": nonce,
        "gas": 21000,
        "gasPrice": gas_price,
        "chainId": SEPOLIA_CHAIN_ID,
        "data": "0x" + data_hash.hex(),
    }

    signed_tx = w3.eth.account.sign_transaction(tx, account.key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

    print(f"  [blockchain] Genesis tx: {tx_hash.hex()}")
    print(f"  [blockchain] Block: {receipt['blockNumber']}")

    return tx_hash.hex()


def record_verification(face_encoding_hash: str, match_url: str, platform: str, w3=None) -> dict:

    if w3 is None:
        w3 = _get_web3()

    account = _get_account(w3)

    verification_data = json.dumps({
        "face_hash": face_encoding_hash,
        "match_url": match_url,
        "platform": platform,
        "timestamp": int(time.time()),
    }, sort_keys=True)

    data_bytes = hashlib.sha256(verification_data.encode()).digest()
    data_hex = "0x" + data_bytes.hex()

    prefix = b"FACEVERIFY:"
    payload = prefix + data_bytes
    payload_hex = "0x" + payload.hex()

    nonce = w3.eth.get_transaction_count(account.address)
    gas_price = w3.eth.gas_price

    tx = {
        "from": account.address,
        "to": account.address,
        "value": 0,
        "nonce": nonce,
        "gas": 25000,
        "gasPrice": gas_price,
        "chainId": SEPOLIA_CHAIN_ID,
        "data": payload_hex,
    }

    signed_tx = w3.eth.account.sign_transaction(tx, account.key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    etherscan_url = f"https://sepolia.etherscan.io/tx/{tx_hash.hex()}"

    result = {
        "tx_hash": tx_hash.hex(),
        "block_number": receipt["blockNumber"],
        "gas_used": receipt["gasUsed"],
        "status": "success" if receipt.get("status") == 1 else "failed",
        "etherscan_url": etherscan_url,
        "verification_data": json.loads(verification_data),
        "on_chain_data_hash": data_hex,
        "network": "ethereum-sepolia",
        "chain_id": SEPOLIA_CHAIN_ID,
        "verifier_address": account.address,
    }

    print(f"  [blockchain] TX: {tx_hash.hex()}")
    print(f"  [blockchain] Block: {receipt['blockNumber']}")
    print(f"  [blockchain] Gas: {receipt['gasUsed']}")
    print(f"  [blockchain] Etherscan: {etherscan_url}")

    return result


def verify_on_chain(tx_hash: str, w3=None) -> dict:
    if w3 is None:
        w3 = _get_web3()

    tx = w3.eth.get_transaction(tx_hash)
    receipt = w3.eth.get_transaction_receipt(tx_hash)

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
                "block_number": receipt["blockNumber"],
                "timestamp": receipt.get("blockNumber"),  # block number as proxy
                "from": tx["from"],
                "to": tx["to"],
                "status": "success" if receipt.get("status") == 1 else "failed",
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
