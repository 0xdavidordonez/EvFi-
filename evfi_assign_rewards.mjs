import fs from "node:fs";
import path from "node:path";

import { ethers } from "ethers";

function loadEnvFile(filePath = ".env") {
  const resolved = path.resolve(process.cwd(), filePath);
  if (!fs.existsSync(resolved)) {
    return;
  }

  const contents = fs.readFileSync(resolved, "utf8");
  for (const rawLine of contents.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) {
      continue;
    }

    const [key, ...rest] = line.split("=");
    const value = rest.join("=").trim().replace(/^['"]|['"]$/g, "");
    if (!(key in process.env)) {
      process.env[key.trim()] = value;
    }
  }
}

function parseArgs(argv) {
  const parsed = {};
  for (let i = 0; i < argv.length; i += 1) {
    const item = argv[i];
    if (!item.startsWith("--")) {
      continue;
    }

    const key = item.slice(2);
    parsed[key] = argv[i + 1];
    i += 1;
  }

  return parsed;
}

loadEnvFile();

const logs = [];

function logStep(message, extra) {
  logs.push(extra ? `${message} ${JSON.stringify(extra)}` : message);
}

function serializeError(error) {
  return {
    code: error?.code || "ASSIGN_REWARD_ERROR",
    reason: error?.reason || error?.shortMessage || error?.message || "Reward assignment failed",
    message: error?.message || String(error),
    stack: error?.stack || "",
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const wallet = args.wallet;
  const amount = args.amount;
  const batchId = args["batch-id"] || `evfi-demo-${new Date().toISOString()}`;

  if (!wallet || !ethers.isAddress(wallet)) {
    throw new Error("Provide a valid --wallet 0x... address");
  }

  if (!amount || Number(amount) <= 0) {
    throw new Error("Provide a positive --amount value");
  }

  const rpcUrl = process.env.SEPOLIA_RPC_URL;
  const tokenAddress = process.env.EVFI_TOKEN_ADDRESS;
  const rewardsAddress = process.env.EVFI_REWARDS_ADDRESS;
  const signerKey = process.env.REWARD_MANAGER_PRIVATE_KEY || process.env.DEPLOYER_PRIVATE_KEY;

  if (!rpcUrl || !rewardsAddress || !tokenAddress || !signerKey) {
    throw new Error("SEPOLIA_RPC_URL, EVFI_TOKEN_ADDRESS, EVFI_REWARDS_ADDRESS, and REWARD_MANAGER_PRIVATE_KEY or DEPLOYER_PRIVATE_KEY are required");
  }

  logStep("Telemetry fetched");
  logStep("Reward calculated:", { amount });
  logStep("Wallet:", { wallet });
  logStep("Token address:", { tokenAddress });
  logStep("Rewards address:", { rewardsAddress });

  const normalizedKey = signerKey.startsWith("0x") ? signerKey : `0x${signerKey}`;
  const provider = new ethers.JsonRpcProvider(rpcUrl);
  const signer = new ethers.Wallet(normalizedKey, provider);
  const network = await provider.getNetwork();
  logStep("Network:", { chainId: Number(network.chainId) });
  if (Number(network.chainId) !== 11155111) {
    throw new Error("Reward manager is not connected to Sepolia.");
  }

  const [tokenCode, rewardsCode] = await Promise.all([
    provider.getCode(tokenAddress),
    provider.getCode(rewardsAddress),
  ]);
  if (tokenCode === "0x") {
    throw new Error("Token contract not deployed.");
  }
  if (rewardsCode === "0x") {
    throw new Error("Rewards contract not deployed.");
  }

  const rewardsAbi = [
    "function REWARD_MANAGER_ROLE() view returns (bytes32)",
    "function hasRole(bytes32 role, address account) view returns (bool)",
    "function availableRewardsBalance() view returns (uint256)",
    "function assignRewardsBatch(address[] accounts, uint256[] amounts, string batchId)",
  ];

  const rewards = new ethers.Contract(rewardsAddress, rewardsAbi, signer);
  const rewardManagerRole = await rewards.REWARD_MANAGER_ROLE();
  const isAuthorized = await rewards.hasRole(rewardManagerRole, signer.address);
  if (!isAuthorized) {
    throw new Error("Wallet is not authorized to mint tokens.");
  }

  const tokenAmount = ethers.parseUnits(String(amount), 18);
  const availableBalance = await rewards.availableRewardsBalance();
  if (availableBalance < tokenAmount) {
    throw new Error(`Rewards contract is underfunded. Available: ${ethers.formatUnits(availableBalance, 18)} EVFI.`);
  }

  try {
    await rewards.assignRewardsBatch.estimateGas([wallet], [tokenAmount], batchId);
  } catch (error) {
    logStep("Gas estimation failed", serializeError(error));
    throw new Error(`Transaction failed during gas estimation. ${error?.shortMessage || error?.reason || error?.message || ""}`.trim());
  }

  logStep("Submitting transaction...");
  const tx = await rewards.assignRewardsBatch([wallet], [tokenAmount], batchId);
  logStep("Transaction hash:", { hash: tx.hash });
  const receipt = await tx.wait();
  logStep("Transaction confirmed", { blockNumber: receipt.blockNumber, status: receipt.status });

  console.log(
    JSON.stringify(
      {
        ok: true,
        wallet,
        amount,
        batchId,
        txHash: tx.hash,
        receipt,
        logs,
      },
      null,
      2,
    ),
  );
}

try {
  await main();
} catch (error) {
  const payload = {
    ok: false,
    error: serializeError(error),
    logs,
  };
  console.error(JSON.stringify(payload, null, 2));
  process.exit(1);
}
