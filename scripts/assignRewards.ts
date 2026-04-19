import fs from "node:fs";
import path from "node:path";

import { ethers } from "hardhat";

type RewardInput = {
  wallet: string;
  score?: number;
  rewardTokens?: string;
};

function ensureAddress(value: string) {
  if (!ethers.isAddress(value)) {
    throw new Error(`Invalid wallet address: ${value}`);
  }

  return value;
}

async function main() {
  const rewardsAddress = process.env.EVFI_REWARDS_ADDRESS;
  if (!rewardsAddress) {
    throw new Error("EVFI_REWARDS_ADDRESS is required");
  }

  const batchPath = path.resolve(
    process.cwd(),
    process.env.REWARD_BATCH_PATH || "data/demo-weekly-scores.example.json",
  );
  const batchId = process.env.REWARD_BATCH_ID || `batch-${new Date().toISOString().slice(0, 10)}`;

  const rawFile = fs.readFileSync(batchPath, "utf8");
  const participants = JSON.parse(rawFile) as RewardInput[];
  if (!Array.isArray(participants) || participants.length === 0) {
    throw new Error("Reward batch file must be a non-empty JSON array");
  }

  const rewards = await ethers.getContractAt("EvFiRewards", rewardsAddress);
  const weeklyPool = await rewards.weeklyRewardPool();
  const scoreTotal = participants.reduce((sum, participant) => sum + BigInt(participant.score ?? 0), 0n);

  const accounts: string[] = [];
  const amounts: bigint[] = [];

  for (const participant of participants) {
    accounts.push(ensureAddress(participant.wallet));

    if (participant.rewardTokens) {
      amounts.push(ethers.parseUnits(participant.rewardTokens, 18));
      continue;
    }

    if (!participant.score || scoreTotal === 0n) {
      throw new Error("Each participant needs rewardTokens or a positive score");
    }

    amounts.push((weeklyPool * BigInt(participant.score)) / scoreTotal);
  }

  const tx = await rewards.assignRewardsBatch(accounts, amounts, batchId);
  console.log(`Submitted ${batchId}: ${tx.hash}`);
  await tx.wait();

  const totalAssigned = amounts.reduce((sum, amount) => sum + amount, 0n);
  console.log(
    `Assigned ${ethers.formatUnits(totalAssigned, 18)} EVFI across ${accounts.length} wallets using ${batchPath}`,
  );
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
