import os
import sys
import json
import time
import io
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))

from detector import detect_and_encode, save_face_crop
from reverse_search import reverse_image_search, pick_best_match
from blockchain import record_verification, verify_on_chain, canonical_hash, _get_web3


def banner(text: str):
    width = 60
    print("\n" + "=" * width)
    print(f"  {text}")
    print("=" * width)


def run_pipeline(image_path: str) -> dict:
    result = {
        "input_image": str(Path(image_path).resolve()),
        "steps": {},
        "success": False,
        "error": None,
    }

    banner("STEP 1: Face Detection & Encoding")
    print(f"  Input: {image_path}")
    t0 = time.time()
    face = detect_and_encode(image_path)
    elapsed = round(time.time() - t0, 2)
    face["elapsed_seconds"] = elapsed

    if not face["face_detected"]:
        msg = f"No face detected: {face.get('error', 'unknown')}"
        print(f"  [FAIL] {msg}")
        print("  Pipeline stopped - face identification is required.")
        result["steps"]["face_detection"] = face
        result["error"] = msg
        result["success"] = False
        return result

    print(f"  [OK]   Face detected  |  model={face['model']}  |  {elapsed}s")
    print(f"         Encoding hash : {face['encoding_hash'][:32]}...")
    print(f"         Bounding box  : {face['face_location']}")
    result["steps"]["face_detection"] = {
        "face_detected": True,
        "encoding_hash": face["encoding_hash"],
        "model": face["model"],
        "face_location": face["face_location"],
        "elapsed_seconds": elapsed,
    }

    try:
        face_crop_path = save_face_crop(image_path, face["face_location"])
        print(f"  Face crop saved : {face_crop_path}")
    except Exception as e:
        print(f"  [WARN] Face crop failed ({e}), using full image")
        face_crop_path = str(Path(image_path).resolve())
    result["steps"]["face_detection"]["face_crop"] = face_crop_path

    banner("STEP 2: Reverse Image Search")
    print("  Search input: detected face crop")
    t0 = time.time()
    serpapi_key = os.getenv("SERPAPI_KEY")
    search_result = reverse_image_search(face_crop_path, serpapi_key=serpapi_key)
    if not search_result["matches"]:
        print("  No matches on face crop, retrying with full image...")
        search_result = reverse_image_search(image_path, serpapi_key=serpapi_key)
    elapsed = round(time.time() - t0, 2)

    n_matches = search_result["total_unique"]
    print(f"  Engines tried : {', '.join(search_result['engines'])}")
    print(f"  Unique matches: {n_matches}  (raw: {search_result['total_raw']})  |  {elapsed}s")

    if not search_result["matches"]:
        msg = "No social-media matches found via reverse image search"
        print(f"  [FAIL] {msg}")
        result["error"] = msg
        result["steps"]["reverse_search"] = {
            "engines": search_result["engines"],
            "matches": [],
            "elapsed_seconds": elapsed,
        }
        return result

    for i, m in enumerate(search_result["matches"][:5], 1):
        print(f"  #{i}  [{m['platform']}] {m['url'][:80]}")

    best_match = pick_best_match(search_result["matches"])
    if not best_match:
        msg = "No reachable social-media post found (post-level URL required)"
        print(f"  [FAIL] {msg}")
        result["error"] = msg
        result["steps"]["reverse_search"] = {
            "engines": search_result["engines"],
            "matches": search_result["matches"],
            "elapsed_seconds": elapsed,
        }
        return result
    print(f"  [OK] Real social-media post found")
    print(f"         Platform : {best_match['platform']}")
    print(f"         Post URL : {best_match['url']}")
    result["steps"]["reverse_search"] = {
        "engines": search_result["engines"],
        "total_unique": n_matches,
        "matches": search_result["matches"],
        "best_match": best_match,
        "elapsed_seconds": elapsed,
    }

    banner("STEP 3: Blockchain Upload (Ethereum Sepolia)")

    rpc_url = os.getenv("SEPOLIA_RPC_URL")
    private_key = os.getenv("PRIVATE_KEY")

    if not rpc_url or not private_key:
        msg = (
            "Blockchain recording skipped – SEPOLIA_RPC_URL / PRIVATE_KEY not set.\n"
            "  To enable:\n"
            "    1. Get a free RPC URL from https://alchemy.com\n"
            "    2. Export your wallet private key (with Sepolia ETH)\n"
            "    3. Add both to face_verify/.env\n"
            "  The face + search results are still valid without on-chain record."
        )
        print(f"  [SKIP] {msg.splitlines()[0]}")
        for line in msg.splitlines()[1:]:
            print(f"         {line}")
        result["steps"]["blockchain"] = {"skipped": True, "reason": "env vars missing"}
    else:
        t0 = time.time()
        try:
            w3 = _get_web3()
            chain_id = w3.eth.chain_id
            latest_block = w3.eth.block_number
            print(f"  Connected to chain {chain_id}  |  latest block: {latest_block}")

            print("  Recording discovered post fingerprint...")
            chain_result = record_verification(
                face_encoding_hash=face["encoding_hash"],
                match_url=best_match["url"],
                platform=best_match["platform"],
                title=best_match.get("title", ""),
                source=best_match.get("source", ""),
                w3=w3,
            )
            elapsed = round(time.time() - t0, 2)
            chain_result["elapsed_seconds"] = elapsed
            result["steps"]["blockchain"] = chain_result
        except Exception as e:
            elapsed = round(time.time() - t0, 2)
            err_msg = str(e)
            print(f"  [FAIL] Blockchain error: {err_msg}")
            result["steps"]["blockchain"] = {
                "error": err_msg,
                "elapsed_seconds": elapsed,
            }

    banner("STEP 4: ON-CHAIN RE-VERIFICATION")
    blockchain_step = result.get("steps", {}).get("blockchain", {})
    if "tx_hash" in blockchain_step:
        try:
            t0 = time.time()
            tx_hash = blockchain_step["tx_hash"]
            print("  Transaction retrieved from Ethereum Sepolia")
            print(f"  TX: 0x{tx_hash.removeprefix('0x')}")
            print("")
            print("  Discovered post:")
            print(f"  Platform       : {best_match['platform']}")
            print(f"  URL            : {best_match['url']}")
            print("")
            stored_data = blockchain_step.get("verification_data", {})
            recomputed = canonical_hash(stored_data)
            print("  Recomputed fingerprint:")
            print(f"  {recomputed}")
            onchain = verify_on_chain(tx_hash, w3=w3)
            remote_hash = onchain.get("data_hash", "")
            onchain_status = onchain.get("status", "")
            print("")
            print("  On-chain fingerprint:")
            print(f"  {remote_hash}")
            print(f"  On-chain status: {onchain_status}")
            print("")
            mined = bool(onchain.get("found") and onchain_status == "success")
            verified = bool(mined and recomputed.lower() == remote_hash.lower())
            elapsed = round(time.time() - t0, 2)
            if verified:
                print("  [OK] HASH MATCH")
                print("  [OK] DATA VERIFIED")
                print("  [OK] TAMPER CHECK PASSED")
            elif not mined:
                print("  [FAIL] Transaction not yet mined - cannot declare VERIFIED")
            else:
                print("  [FAIL] MISMATCH - local hash does not match on-chain record")
            result["steps"]["reverification"] = {
                "verified": verified,
                "recomputed_hash": recomputed,
                "onchain_hash": remote_hash,
                "onchain_detail": onchain,
                "elapsed_seconds": elapsed,
            }
        except Exception as e:
            err_msg = str(e)
            print(f"  [FAIL] Re-verification error: {err_msg}")
            result["steps"]["reverification"] = {
                "verified": False,
                "error": err_msg,
            }
    else:
        print("  [SKIP] No transaction to verify")
        result["steps"]["reverification"] = {"verified": False, "skipped": True}

    banner("PIPELINE COMPLETE")
    blockchain_step = result.get("steps", {}).get("blockchain", {})
    reverify_step = result.get("steps", {}).get("reverification", {})
    face_ok = bool(result.get("steps", {}).get("face_detection", {}).get("face_detected", False))
    match_ok = bool(best_match and best_match.get("url"))
    recorded_ok = bool("tx_hash" in blockchain_step and blockchain_step.get("status") in ("success", "pending"))
    mined_ok = bool("tx_hash" in blockchain_step and blockchain_step.get("status") == "success")
    verified_ok = bool(reverify_step.get("verified", False))
    result["success"] = bool(face_ok and match_ok and mined_ok and verified_ok)
    result["summary"] = {
        "face_detected": face_ok,
        "web_match_found": match_ok,
        "blockchain_recorded": mined_ok,
        "blockchain_verified": verified_ok,
        "face_hash": face["encoding_hash"],
        "best_match_url": best_match["url"],
        "platform": best_match["platform"],
        "total_matches": n_matches,
    }
    print(json.dumps(result["summary"], indent=2))

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <image_path>")
        print()
        print("Required .env variables for full pipeline:")
        print("  SEPOLIA_RPC_URL  – Alchemy RPC for Ethereum Sepolia")
        print("  PRIVATE_KEY      – Wallet private key (with Sepolia ETH)")
        print("Optional:")
        print("  SERPAPI_KEY       – SerpAPI key for Google Lens backup")
        sys.exit(1)

    output = run_pipeline(sys.argv[1])

    out_path = Path(__file__).parent / "pipeline_result.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Full result saved to: {out_path}")
