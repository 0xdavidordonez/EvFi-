# EvFi

This repo is now the single project for:

- Sepolia smart contracts
- Hardhat deployment and tests
- Tesla Fleet API Flask app
- Sepolia wallet connect and EVFI claim flow

The old `tesla-fleet-api-demo` clone is no longer required for active development.

## Structure

- `contracts/`
  - `EvFiToken.sol`
  - `EvFiRewards.sol`
- `scripts/`
  - `deploy.ts`
  - `assignRewards.ts`
- `evfi_fleet_core.py`
  - Flask Tesla telemetry app and wallet-integrated dashboard
- `evfi_fleet_app.py`
  - preferred Python entrypoint
- `evfi_assign_rewards.mjs`
  - Node helper used by the Flask app to assign onchain rewards
- `static/`
  - wallet script and dashboard assets
- `.well-known/appspecific/`
  - Tesla public key path for fleet integration

## Environment

The repo uses one `.env` file for both contract deployment and the Flask app.

Key variables:

- `DEPLOYER_PRIVATE_KEY`
- `REWARD_MANAGER_PRIVATE_KEY`
- `SEPOLIA_RPC_URL`
- `ADMIN_ADDRESS`
- `TREASURY_ADDRESS`
- `EVFI_TOKEN_ADDRESS`
- `EVFI_REWARDS_ADDRESS`
- `PORT`
- `TESLA_CLIENT_ID`
- `TESLA_CLIENT_SECRET`
- `TESLA_REDIRECT_URI`

## Install

Node dependencies for contracts and reward assignment:

```bash
npm install
```

Python dependencies for the Flask app:

```bash
pip install -r requirements.txt
```

## Deploy Contracts

```bash
npm run deploy:sepolia
```

Deployment output is written to:

- `deployments/sepolia.json`

## Run The App

```bash
python evfi_fleet_app.py
```

The local Flask server runs on:

- `http://localhost:8091`

Your Tesla OAuth callback is configured to:

- `https://unautumnal-unusably-johnathon.ngrok-free.dev/auth/callback`

Use that ngrok domain in Tesla Developer settings:

- Allowed Origin(s): `https://unautumnal-unusably-johnathon.ngrok-free.dev`
- Allowed Redirect URI(s): `https://unautumnal-unusably-johnathon.ngrok-free.dev/auth/callback`
- Allowed Returned URL(s): `https://unautumnal-unusably-johnathon.ngrok-free.dev/`

## Current Flow

1. Tesla OAuth authenticates the user.
2. Flask reads live vehicle telemetry.
3. Mileage history stays offchain in SQLite as the scoring ledger.
4. The dashboard connects a Sepolia wallet.
5. The app reads `EVFI` balance and pending rewards from `EvFiRewards`.
6. Admin/test reward assignment can reserve rewards onchain.
7. The user claims EVFI directly from the wallet.

## Demo Screenshots

Add your screenshots to `docs/screenshots/` and update the filenames below when ready.

![Dashboard overview](docs/screenshots/dashboard-overview.png)
![Wallet connected](docs/screenshots/wallet-connected.png)
![Rewards claim flow](docs/screenshots/rewards-claim-flow.png)

## Main Entry Points

- Python app: `evfi_fleet_app.py`
- Python core module: `evfi_fleet_core.py`
- Contract deployment: `npm run deploy:sepolia`
- Contract tests: `npm test`

## Next

The repo is consolidated. Next steps can focus on:

- aesthetic cleanup
- dashboard refinement
- naming cleanup inside the Python module
- GitHub repo initialization and publish prep
