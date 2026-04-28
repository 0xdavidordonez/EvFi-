import { ethers } from "ethers";
import * as dotenv from "dotenv";

dotenv.config();

const GENERATED_FEES_POOL_ABI = [
  "function evfiToken() view returns (address)",
  "function owner() view returns (address)",
  "function tokenBalance() view returns (uint256)",
];

const STAKING_ABI = [
  "function evfiToken() view returns (address)",
  "function generatedFeesPool() view returns (address)",
  "function owner() view returns (address)",
  "function earlyUnstakePenaltyBps() view returns (uint16)",
  "function allowedLockDurations(uint64) view returns (bool)",
];

function requireAddress(value: string | undefined, name: string) {
  if (!value || !ethers.isAddress(value)) {
    throw new Error(`${name} must be a valid address.`);
  }
  return ethers.getAddress(value);
}

function assertEqualAddress(actual: string, expected: string, label: string) {
  if (ethers.getAddress(actual) !== ethers.getAddress(expected)) {
    throw new Error(`${label} mismatch: got ${actual}, expected ${expected}`);
  }
}

async function main() {
  const rpcUrl = process.env.SEPOLIA_RPC_URL || process.env.ALCHEMY_SEPOLIA_URL;
  if (!rpcUrl) {
    throw new Error("SEPOLIA_RPC_URL is required.");
  }

  const tokenAddress = requireAddress(process.env.EVFI_TOKEN_ADDRESS, "EVFI_TOKEN_ADDRESS");
  const generatedFeesPoolAddress = requireAddress(
    process.env.GENERATED_FEES_POOL_ADDRESS,
    "GENERATED_FEES_POOL_ADDRESS",
  );
  const stakingAddress = requireAddress(process.env.EVFI_STAKING_CONTRACT_ADDRESS, "EVFI_STAKING_CONTRACT_ADDRESS");
  const expectedOwner = requireAddress(process.env.ADMIN_ADDRESS || process.env.DEFAULT_WALLET_ADDRESS, "ADMIN_ADDRESS");
  const expectedPenaltyBps = BigInt(Number.parseInt(process.env.EARLY_UNSTAKE_PENALTY_BPS || "1000", 10));

  const provider = new ethers.JsonRpcProvider(rpcUrl);
  const network = await provider.getNetwork();
  if (network.chainId !== 11155111n) {
    throw new Error(`Expected Sepolia 11155111, got chain ${network.chainId}.`);
  }

  const generatedFeesPool = new ethers.Contract(generatedFeesPoolAddress, GENERATED_FEES_POOL_ABI, provider);
  const staking = new ethers.Contract(stakingAddress, STAKING_ABI, provider);

  assertEqualAddress(await generatedFeesPool.evfiToken(), tokenAddress, "GeneratedFeesPool token");
  assertEqualAddress(await generatedFeesPool.owner(), expectedOwner, "GeneratedFeesPool owner");
  assertEqualAddress(await staking.evfiToken(), tokenAddress, "EVFIStaking token");
  assertEqualAddress(await staking.generatedFeesPool(), generatedFeesPoolAddress, "EVFIStaking generated fees pool");
  assertEqualAddress(await staking.owner(), expectedOwner, "EVFIStaking owner");

  const penaltyBps = BigInt(await staking.earlyUnstakePenaltyBps());
  if (penaltyBps !== expectedPenaltyBps) {
    throw new Error(`Penalty mismatch: got ${penaltyBps}, expected ${expectedPenaltyBps}`);
  }

  for (const duration of [21600, 86400, 604800]) {
    if (!(await staking.allowedLockDurations(duration))) {
      throw new Error(`Lock duration ${duration} is not enabled.`);
    }
  }

  console.log("Sepolia staking deployment verified");
  console.log(`EVFI token: ${tokenAddress}`);
  console.log(`GeneratedFeesPool: ${generatedFeesPoolAddress}`);
  console.log(`EVFIStaking: ${stakingAddress}`);
  console.log(`Generated fees balance: ${ethers.formatUnits(await generatedFeesPool.tokenBalance(), 18)} EVFI`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
