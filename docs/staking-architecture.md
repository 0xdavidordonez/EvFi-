## EVFI Staking Architecture

### Source of truth
- Telemetry and rewards remain offchain.
- EVFI staking state moves onchain.
- The backend may cache stake rows for analytics and audit, but the contract is authoritative.

### Contracts
- `EVFIStaking.sol`
  - accepts EVFI deposits
  - stores per-wallet stake positions
  - supports amount-based staking
  - supports short testnet lock periods
  - allows instant early unstake with a `10%` penalty
- `GeneratedFeesPool.sol`
  - receives early-unstake penalty fees
  - acts as the treasury sink for `generated_fees`

### Lock model
- Default allowed locks:
  - `6 hours`
  - `1 day`
  - `7 days`
- Lock durations are owner-configurable.
- Unstake is always immediate.
- If unstake happens before `unlockTime`, the penalty is applied.

### Penalty model
- Early unstake penalty default: `1000 bps` (`10%`)
- Penalty amount is transferred to `generated_fees`
- Net amount is returned to the staker immediately

### Frontend flow
1. Connect wallet
2. Choose amount
3. Choose lock duration
4. Check EVFI allowance
5. If allowance is too low, call `approve`
6. Call `stake`
7. Reflect pending / success / error state
8. Read real onchain positions for dashboard state

### What gets automated
- User staking and unstaking should be wallet-signed. No API key textbox.
- Scheduled or admin functions should use a server-held relayer or automation service.

### What cannot be self-triggered by the contract alone
- Smart contracts do not wake up on their own.
- Anything periodic or administrative still needs a caller:
  - backend worker
  - relayer
  - automation service
