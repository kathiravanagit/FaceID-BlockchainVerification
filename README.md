# Face ID + Blockchain Verification Pipeline

A pipeline that detects and encodes a face from a photo, finds a real matching social media post via genuine reverse-image search, and writes that match to a blockchain as a tamper-evident record.

## Architecture

```
┌─────────────────┐    ┌──────────────────────┐    ┌──────────────────┐
│  Input Image     │───▶│  Face Detection       │───▶│  Reverse Image   │
│  (any photo)     │    │  (deepface / ArcFace) │    │  Search (Yandex) │
└─────────────────┘    └──────────────────────┘    └────────┬─────────┘
                                                             │
                                                   ┌────────▼─────────┐
                                                   │  Blockchain       │
                                                   │  Record           │
                                                   │  (Sepolia Testnet)│
                                                   └──────────────────┘
```

## How It Works

### Step 1: Face Detection & Encoding
- Uses **deepface** with the **ArcFace** model for face detection and 128-d embedding
- Generates a SHA-256 hash of the face encoding for blockchain storage
- Returns bounding box coordinates

### Step 2: Reverse Image Search (Genuine)
- **Primary**: Yandex Reverse Image Search (free, no API key)
  - Uses Playwright headless browser for JavaScript-rendered results
  - Uploads the image and parses search results for social media links
- **Optional**: SerpAPI Google Lens (requires free API key)
  - 100 free searches/month at https://serpapi.com
- Deduplicates results and identifies platforms (Facebook, Twitter/X, Instagram, etc.)

### Step 3: Blockchain Verification
- Records the match on **Ethereum Sepolia testnet**
- Embeds a `FACEVERIFY:` prefix + SHA-256 hash of the verification data in a transaction
- Transaction includes: face encoding hash, social media URL, platform, timestamp
- All records verifiable on [Etherscan (Sepolia)](https://sepolia.etherscan.io)

## How to Run

### Prerequisites
- Python 3.10+
- An input image containing a face

### 1. Install Dependencies
```bash
cd face_verify
pip install -r requirements.txt
playwright install chromium
```

### 2. Set Up Environment (for blockchain recording)
1. Get a free Sepolia RPC URL from [Alchemy](https://alchemy.com)
2. Get testnet ETH from [Sepolia Faucet](https://sepoliafaucet.com)
3. Copy `.env.example` to `.env` and fill in:
```
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
|----------|-------|
| **Network** | Ethereum Sepolia (testnet) |
| **Chain ID** | 11155111 |
| **Record Method** | Raw transaction with embedded data |
| **Data Format** | `FACEVERIFY:` prefix + SHA-256 of verification payload |
| **Verification** | Via Etherscan URL in output |

Each verification produces a transaction like:
```
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
    }
  }
}
```

## Known Limitations

1. **Reverse Image Search**: Yandex uses JavaScript-rendered results; Playwright handles this but may be blocked by CAPTCHAs. SerpAPI backup available with free key.
2. **Blockchain**: Requires Sepolia testnet ETH (~0.001 ETH per record). Faucets: https://sepoliafaucet.com
3. **Face Detection**: Requires at least one clear face in the image. Multiple faces: pipeline uses the first detected. Synthetic/drawn faces may not be detected.
4. **Encoding Model**: ArcFace embeddings are model-specific; not portable to other systems.
5. **No Smart Contract**: Verification data is stored as raw transaction data, not via a structured contract. A contract deployment would allow richer on-chain queries.
6. **Rate Limits**: Yandex may rate-limit or CAPTCHA after many automated requests.
7. **Platform Detection**: Based on URL domain matching; may miss shortened URLs.
8. **Real Photos Required**: For reverse image search to find social media matches, the input image must be of a real person whose photo exists on social media.

## Stack

- **Face Detection**: deepface + ArcFace + OpenCV
- **Reverse Image Search**: Yandex (Playwright headless browser) + BeautifulSoup
- **Blockchain**: Ethereum Sepolia + web3.py + eth-account
