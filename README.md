# Face ID + Blockchain Verification Pipeline

I built this because photos travel fast online and screenshots prove nothing. Give this pipeline any face photo and it detects the face, hunts down a real social media post containing it through live reverse-image search, then fingerprints that find onto Ethereum Sepolia — so anyone can re-verify the record on-chain later. No website, no shortcuts: just a command-line pipeline that does the whole thing end to end.

## Architecture

```text
┌─────────────────┐    ┌──────────────────────┐    ┌──────────────────┐
│  Input Image     │───▶│  Face Detection       │───▶│  Reverse Image   │
│  (any photo)     │    │  (deepface / ArcFace) │    │  Search (Yandex + │
└─────────────────┘    └──────────────────────┘    │  SerpAPI Lens)    │
                                                   └────────┬─────────┘
                                                            │
                                                   ┌────────▼─────────┐
                                                   │  STEP 3 Blockchain│
                                                   │  Upload (Sepolia) │
                                                   └────────┬─────────┘
                                                            │
                                                   ┌────────▼─────────┐
                                                   │  STEP 4 Re-Verify │
                                                   │  Retrieve tx,     │
                                                   │  recompute hash,  │
                                                   │  compare → VERIFIED│
                                                   └──────────────────┘
```

## How It Works

### Step 1: Face Detection & Encoding

- Uses **deepface** with the **ArcFace** model for face detection and face embedding
- Saves a padded face crop and uses the crop as the primary reverse-search input
- Generates a SHA-256 hash of the face encoding for blockchain storage
- Returns bounding box coordinates

### Step 2: Genuine Reverse Image Search

- Searches the **detected face crop first**, falls back to the full image
- **Yandex** Reverse Image Search (free, no API key, Playwright headless browser)
- **SerpAPI Google Lens** backup (requires free API key, 100 searches/month)
- Filters to real post URLs (Instagram /p/ or /reel/, X /status/, TikTok /video/, YouTube /watch/, Reddit /comments/, etc.)
- Picks the first reachable post-level match as the best match

### Step 3: Blockchain Upload

- Records the match on **Ethereum Sepolia testnet**
- Stores a SHA-256 fingerprint of the discovered post metadata, including the matched URL, platform, search source and available result metadata
- Embeds a `FACEVERIFY:` prefix + fingerprint in a transaction
- All records viewable on [Etherscan (Sepolia)](https://sepolia.etherscan.io)

### Step 4: On-Chain Re-Verification

- Retrieves the transaction back from Sepolia via `verify_on_chain(tx_hash)`
- Independently recomputes the SHA-256 fingerprint from the stored verification payload
- Compares recomputed hash == on-chain hash and prints `HASH MATCH / DATA VERIFIED / TAMPER CHECK PASSED`
- Result stored in `pipeline_result.json` under `steps.reverification`
- Pipeline `success` is true only when face detected, post found, tx mined, and verification passed

## How to Run

### Prerequisites

- Python 3.10+
- An input image containing a face

### 1. Install Dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Set Up Environment (for blockchain recording)

1. Get a free Sepolia RPC URL from [Alchemy](https://alchemy.com)
2. Get testnet ETH from [Sepolia Faucet](https://sepoliafaucet.com)
3. Copy `.env.example` to `.env` and fill in:

```env
SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/YOUR_KEY
PRIVATE_KEY=0xYOUR_PRIVATE_KEY
```

### 3. Run the Pipeline

```bash
python pipeline.py <path/to/face_image.jpg>
```

Example:

```bash
python pipeline.py photo.jpg
```

The pipeline works **without** blockchain config too — face detection and reverse image search run regardless.

### Individual Modules

```bash
# Face detection only
python detector.py photo.jpg

# Reverse image search only
python reverse_search.py photo.jpg

# Blockchain operations
python blockchain.py deploy
python blockchain.py record <hash> <url> <platform>
python blockchain.py verify <tx_hash>
```

## Blockchain Details

| Property | Value |
| ---------- | ------- |
| **Network** | Ethereum Sepolia (testnet) |
| **Chain ID** | 11155111 |
| **Record Method** | Raw transaction with embedded data |
| **Data Format** | `FACEVERIFY:` prefix + SHA-256 of verification payload |
| **Verification** | Programmatic re-verification: retrieve tx, recompute SHA-256, compare (STEP 4) + Etherscan URL |

Each verification produces a transaction like:

```text
0x FACEVERIFY: <64-byte SHA-256 hash>
```

The full verification data (face hash, URL, platform, timestamp) is in `pipeline_result.json`.

## Output

Results are saved to `pipeline_result.json`:

```json
{
  "input_image": "/path/to/photo.jpg",
  "steps": {
    "face_detection": {
      "face_detected": true,
      "encoding_hash": "a1b2c3...",
      "model": "arcface"
    },
    "reverse_search": {
      "engines": ["yandex"],
      "total_unique": 5,
      "matches": [...],
      "best_match": {"url": "https://...", "platform": "Instagram"}
    },
    "blockchain": {
      "tx_hash": "0x...",
      "block_number": 1234567,
      "etherscan_url": "https://sepolia.etherscan.io/tx/0x..."
    },
    "reverification": {
      "verified": true,
      "local_hash": "0x...",
      "onchain_hash": "0x..."
    }
  }
}
```

## Known Limitations

1. **Search engine rate limits**: Web search relies on external services (Yandex, SerpAPI). Heavy automated traffic can trigger rate limits or CAPTCHAs; Yandex uses JavaScript-rendered results handled via Playwright.
2. **Sepolia RPC delays**: Testnet congestion may delay transaction confirmation. The pipeline waits up to 300s for mining and preserves the tx hash as pending if confirmation times out.
3. **Low-resolution inputs**: Blurry, tiny, or heavily cropped faces lower DeepFace/ArcFace detection accuracy. A clear, front-facing photo works best. Multiple faces: pipeline uses the first detected. Synthetic/drawn faces may not be detected.
4. **Blockchain**: Requires Sepolia testnet ETH (~0.001 ETH per record). Faucets: <https://sepoliafaucet.com>
5. **Encoding Model**: ArcFace embeddings are model-specific; not portable to other systems.
6. **No Smart Contract**: Verification data is stored as raw transaction data, not via a structured contract. A contract deployment would allow richer on-chain queries.
7. **Platform Detection**: Based on URL domain matching; may miss shortened URLs.
8. **Real Photos Required**: For reverse image search to find social media matches, the input image must be of a real person whose photo exists on social media.

## Stack

- **Face Detection**: deepface + ArcFace + OpenCV
- **Reverse Image Search**: Yandex (Playwright headless browser) + BeautifulSoup
- **Blockchain**: Ethereum Sepolia + web3.py + eth-account
