# Codex Handoff

Project: Electrified / EVFI  
Repo: `C:\Users\clawbot_ai\Desktop\EvFi`

## Current Goal
- Finish real Sepolia staking integration
- Keep telemetry and rewards offchain
- Keep staking onchain
- Keep global charge policy only
- User-specific charge preferences are shelved indefinitely

## Current Status
- Contracts compile locally with Hardhat
- Sepolia staking contracts are deployed and verified
- App `.env` is wired to deployed staking addresses
- Local contract and backend tests pass

## What Has Been Completed

### Reward / telemetry system
- Unified weekly reward model
- Fixed reward sync history mileage delta issues
- Fixed repeated MetaMask token prompt behavior
- Fixed wallet disconnect on `Sync Miles`
- Added weekly score breakdown UI
- Added “Why Your Reward Changed” explanation UI
- Added deterministic global charge policy
- Added canonical `charge_sessions` rebuild flow after telemetry sync

### Utility / staking transition
- Added utility/staking UI scaffolding
- Disabled fake app-level staking authority
- Shifted staking design toward real onchain staking

### Staking contracts added
- [EVFIStaking.sol](C:\Users\clawbot_ai\Desktop\EvFi\contracts\EVFIStaking.sol)
- [GeneratedFeesPool.sol](C:\Users\clawbot_ai\Desktop\EvFi\contracts\GeneratedFeesPool.sol)

### Sepolia staking deployment
- `EVFI_TOKEN_ADDRESS=0xE8d308592562a1A3BdBb2F57BD52633Dd46fa47F`
- `GENERATED_FEES_POOL_ADDRESS=0x0dd87535b9D9f23BAd0518305a7B09CC58b9833E`
- `EVFI_STAKING_CONTRACT_ADDRESS=0x6afF4fb32EE5E3B05eD2bFfD1664774AD4406E18`
- Deployment metadata: [sepolia-staking.json](C:\Users\clawbot_ai\Desktop\EvFi\deployments\sepolia-staking.json)

### Staking docs added
- [staking-architecture.md](C:\Users\clawbot_ai\Desktop\EvFi\docs\staking-architecture.md)
- [sepolia-staking-deploy-runbook.md](C:\Users\clawbot_ai\Desktop\EvFi\docs\sepolia-staking-deploy-runbook.md)

## Current Staking Design
- amount-based staking
- short testnet lock periods:
  - `6 hours`
  - `1 day`
  - `7 days`
- early unstake allowed
- early-unstake penalty: `10%`
- penalty routed to separate `generated_fees` pool contract
- DB stake rows are cache/audit only, not authority
- chain state should be the source of truth for reward boost

## Contract Constructors

### GeneratedFeesPool
- constructor:
  - `token_`
  - `initialOwner`

### EVFIStaking
- constructor:
  - `token_`
  - `generatedFeesPool_`
  - `initialOwner`
  - `earlyUnstakePenaltyBps_`

Recommended initial penalty:
- `1000` basis points (`10%`)

## Backend / app changes already made

### Added onchain staking config/state support
In [evfi_fleet_core.py](C:\Users\clawbot_ai\Desktop\EvFi\evfi_fleet_core.py):
- `/api/staking/config`
- `/api/staking/state`
- `/api/staking/audit`

### Added chain-backed staking helpers
In [evfi_fleet_core.py](C:\Users\clawbot_ai\Desktop\EvFi\evfi_fleet_core.py):
- reads staking contract state with Web3 if configured
- derives staking tier from amount thresholds
- uses onchain stake state for `get_active_stake_boost_pct(...)`
- includes `onchainStaking` in utility state

### Added browser staking module
In [evfi-staking.js](C:\Users\clawbot_ai\Desktop\EvFi\static\evfi-staking.js):
- loads MetaMask-based staking UI
- disables legacy fake staking buttons
- checks/switches to Sepolia
- runs `approve`
- runs `stake`
- runs `unstake`
- mirrors txs to backend audit endpoint

### Added ethers loader
Dashboard now includes:
- `https://cdn.jsdelivr.net/npm/ethers@6.13.2/dist/ethers.umd.min.js`

## Env Variables Added / Expected
In [`.env`](C:\Users\clawbot_ai\Desktop\EvFi\.env):

```env
STAKING_MODE=onchain
SEPOLIA_CHAIN_ID=11155111
SEPOLIA_RPC_URL=
EVFI_TOKEN_DECIMALS=18
EVFI_TOKEN_ADDRESS=
EARLY_UNSTAKE_PENALTY_BPS=1000
STAKING_ALLOWED_LOCKS=21600,86400,604800
STAKING_TIER_THRESHOLDS=100:Bronze:5,500:Silver:10,1000:Gold:15
EVFI_STAKING_CONTRACT_ADDRESS=
GENERATED_FEES_POOL_ADDRESS=
```

## Immediate Next Steps
1. Run live MetaMask test:
   - `approve`
   - `stake`
   - `unstake`
2. Verify reward boost updates from onchain stake state in the dashboard after staking
3. Consider verifying source code on Etherscan after ABI/address checks are complete

## Important Constraints / Notes
- Browser flow still requires manual MetaMask confirmation for `approve`, `stake`, and `unstake`
- Current staking browser flow assumes `ethers` is available globally
- Current backend onchain read path requires the Python `web3` package when using `SEPOLIA_RPC_URL`
- `GeneratedFeesPool` balance is currently `0.0 EVFI`; it increases only after an early unstake penalty

## Resume Prompt For New Session

Use this in a fresh Codex chat:

```text
Read C:\Users\clawbot_ai\Desktop\EvFi\docs\codex-handoff.md and continue the EVFI Sepolia staking integration from there.
```
