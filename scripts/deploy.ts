import fs from "node:fs";
import path from "node:path";

import { ethers, network, run } from "hardhat";

function parseTokenAmount(value: string | undefined, fallback: string) {
  return ethers.parseUnits(value || fallback, 18);
}

async function verifyContract(address: string, constructorArguments: unknown[]) {
  if (!process.env.ETHERSCAN_API_KEY || network.name === "hardhat") {
    return;
  }

  try {
    await run("verify:verify", {
      address,
      constructorArguments,
    });
  } catch (error) {
    console.warn(`Verification skipped for ${address}:`, error);
  }
}

async function main() {
  const [deployer] = await ethers.getSigners();
  const adminAddress = process.env.ADMIN_ADDRESS || deployer.address;
  const treasuryAddress = process.env.TREASURY_ADDRESS || deployer.address;
  const maxSupply = parseTokenAmount(process.env.EVFI_MAX_SUPPLY, "1000000000");
  const weeklyRewardPool = parseTokenAmount(process.env.WEEKLY_REWARD_POOL, "10000");
  const initialFunding = parseTokenAmount(process.env.INITIAL_REWARDS_FUNDING, "100000");

  console.log(`Deploying EvFi phase 1 contracts with ${deployer.address} on ${network.name}`);
  console.log(`Admin: ${adminAddress}`);
  console.log(`Treasury: ${treasuryAddress}`);

  const token = await ethers.deployContract("EvFiToken", [adminAddress, treasuryAddress, maxSupply]);
  await token.waitForDeployment();

  const tokenAddress = await token.getAddress();
  console.log(`EvFiToken deployed to ${tokenAddress}`);

  const rewards = await ethers.deployContract("EvFiRewards", [adminAddress, tokenAddress, weeklyRewardPool]);
  await rewards.waitForDeployment();

  const rewardsAddress = await rewards.getAddress();
  console.log(`EvFiRewards deployed to ${rewardsAddress}`);

  if (treasuryAddress.toLowerCase() === deployer.address.toLowerCase() && initialFunding > 0n) {
    const fundingTx = await token.transfer(rewardsAddress, initialFunding);
    await fundingTx.wait();
    console.log(`Funded rewards contract with ${ethers.formatUnits(initialFunding, 18)} EVFI`);
  } else {
    console.log("Treasury is not controlled by the deployer. Fund EvFiRewards manually before assigning rewards.");
  }

  const deployment = {
    network: network.name,
    chainId: (await ethers.provider.getNetwork()).chainId.toString(),
    deployer: deployer.address,
    adminAddress,
    treasuryAddress,
    tokenAddress,
    rewardsAddress,
    maxSupply: maxSupply.toString(),
    weeklyRewardPool: weeklyRewardPool.toString(),
    initialFunding: initialFunding.toString(),
    deployedAt: new Date().toISOString(),
  };

  const deploymentsDir = path.join(process.cwd(), "deployments");
  fs.mkdirSync(deploymentsDir, { recursive: true });
  fs.writeFileSync(path.join(deploymentsDir, `${network.name}.json`), JSON.stringify(deployment, null, 2));

  await verifyContract(tokenAddress, [adminAddress, treasuryAddress, maxSupply]);
  await verifyContract(rewardsAddress, [adminAddress, tokenAddress, weeklyRewardPool]);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
