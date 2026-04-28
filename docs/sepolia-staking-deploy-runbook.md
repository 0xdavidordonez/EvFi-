## Sepolia Staking Deploy Runbook

This runbook covers step 2 and step 3 of the current staking plan:

1. Deploy `GeneratedFeesPool` and `EVFIStaking` to Sepolia
2. Wire the deployed addresses into the app
3. Run a live MetaMask stake / unstake test

### Preconditions
- EVFI token already deployed on Sepolia
- MetaMask wallet funded with Sepolia ETH
- Wallet also holds Sepolia EVFI
- App `.env` has a working `SEPOLIA_RPC_URL`
- Browser can connect to MetaMask

### Current Sepolia deployment

Deployed on 2026-04-27:

```env
EVFI_TOKEN_ADDRESS=0xE8d308592562a1A3BdBb2F57BD52633Dd46fa47F
GENERATED_FEES_POOL_ADDRESS=0x0dd87535b9D9f23BAd0518305a7B09CC58b9833E
EVFI_STAKING_CONTRACT_ADDRESS=0x6afF4fb32EE5E3B05eD2bFfD1664774AD4406E18
```

Deployment metadata is written to `deployments/sepolia-staking.json`.

### Hardhat commands

```powershell
npm run compile
npm run deploy:staking:sepolia
npm run verify:staking:sepolia
```

### Contract deployment order

#### 1. Deploy `GeneratedFeesPool`
Constructor:
- `token_`: EVFI token address
- `initialOwner`: deployer or ops owner wallet

Example constructor values:
- `token_ = EVFI_TOKEN_ADDRESS`
- `initialOwner = YOUR_WALLET`

#### 2. Deploy `EVFIStaking`
Constructor:
- `token_`: EVFI token address
- `generatedFeesPool_`: deployed `GeneratedFeesPool` address
- `initialOwner`: deployer or ops owner wallet
- `earlyUnstakePenaltyBps_`: `1000`

Example constructor values:
- `token_ = EVFI_TOKEN_ADDRESS`
- `generatedFeesPool_ = GENERATED_FEES_POOL_ADDRESS`
- `initialOwner = YOUR_WALLET`
- `earlyUnstakePenaltyBps_ = 1000`

### Post-deploy app config

Fill these values in [`.env`](/C:/Users/clawbot_ai/Desktop/EvFi/.env):

```env
STAKING_MODE=onchain
SEPOLIA_CHAIN_ID=11155111
SEPOLIA_RPC_URL=...
EVFI_TOKEN_DECIMALS=18
EVFI_TOKEN_ADDRESS=0x...
EARLY_UNSTAKE_PENALTY_BPS=1000
STAKING_ALLOWED_LOCKS=21600,86400,604800
STAKING_TIER_THRESHOLDS=100:Bronze:5,500:Silver:10,1000:Gold:15
EVFI_STAKING_CONTRACT_ADDRESS=0x...
GENERATED_FEES_POOL_ADDRESS=0x...
```

### Live MetaMask test plan

#### Stake flow
1. Open dashboard
2. Connect MetaMask
3. Confirm MetaMask is on Sepolia
4. Enter amount, for example `100`
5. Choose lock period:
   - `6h`
   - `1d`
   - `7d`
6. Click `Approve + Stake`
7. Confirm `approve` tx in MetaMask
8. Confirm `stake` tx in MetaMask
9. Refresh or let dashboard reload

Expected results:
- Onchain staking panel shows position
- Total staked increases
- Stake tier reflects threshold hit
- Reward boost matches threshold config
- Utility state reflects chain-backed active stake

#### Early unstake flow
1. Click `Unstake Position`
2. Confirm tx in MetaMask before unlock time

Expected results:
- Position amount decreases or clears
- Dashboard shows reduced total staked
- `previewUnstake` reflected a `10%` penalty
- `GeneratedFeesPool` EVFI balance increases by penalty amount

#### Mature unstake flow
1. Wait until unlock time passes
2. Click `Unstake Position`
3. Confirm tx

Expected results:
- No early penalty
- Full requested amount returns

### What to verify onchain
- `EVFIStaking.totalStaked(wallet)`
- `EVFIStaking.getStakePositionsCount(wallet)`
- `EVFIStaking.getStakePosition(wallet, positionId)`
- `GeneratedFeesPool.tokenBalance()`

### Known current implementation details
- Backend treats chain state as staking authority
- Local DB mirrors actions for audit only
- Frontend loads `ethers` from CDN and uses MetaMask contract writes
- Legacy fake staking buttons are disabled

### What is not covered by this runbook
- automated weekly reward settlement
- admin relayer automation
- Solana support
- production multisig governance
