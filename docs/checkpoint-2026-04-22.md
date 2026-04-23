# EvFi Checkpoint - 2026-04-22

## Current State

- Hardhat 3 Mocha/Ethers contract test setup is fixed.
- TypeScript contract tests execute through `hardhat test`.
- Removed the skipped `test/Counter.ts` starter scaffold.
- Expanded EvFi contract coverage to 13 active passing Mocha tests.
- Verified Python app syntax and contract compilation.
- Confirmed deployed Sepolia EVFI reports `18` decimals and wallet `0x9446D03c7572C05dE3cb7dE5345B51B71aE46492` holds `1168.6979 EVFI`.
- Added wallet metadata registration so MetaMask is prompted to track the deployed EVFI token with the correct `18` decimals.

## Saved Commits

- `1596fba Fix Hardhat 3 Mocha contract test setup`
- `ea426ab Expand EvFi contract test coverage`

## Verification

```powershell
python -m py_compile evfi_fleet_app.py evfi_fleet_core.py
npm run compile
npm test
```

Latest result:

```text
13 passing (13 mocha)
```

## Next Recommended Work

1. Add a concrete V2/V3 roadmap to the repo.
2. Verify Sepolia deployment config and deployed contract addresses.
3. Run or dry-run the Sepolia deployment and reward assignment scripts.
4. Add integration checks around `evfi_assign_rewards.mjs` and the Flask reward assignment path.
5. Decide whether generated artifacts and TypeChain output should remain committed or be regenerated on install/build.
