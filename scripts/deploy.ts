import fs from "node:fs";
import path from "node:path";

import { ethers } from "ethers";
import * as dotenv from "dotenv";

dotenv.config();

type ContractArtifact = {
  abi: unknown[];
  bytecode: string;
};

function normalizePrivateKey(value?: string) {
  if (!value) {
    return undefined;
  }

  return value.startsWith("0x") ? value : `0x${value}`;
}

function parseTokenAmount(value: string | undefined, fallback: string) {
  return ethers.parseUnits(value || fallback, 18);
}

function loadArtifact(contractFile: string, contractName: string): ContractArtifact {
  const artifactPath = path.join(process.cwd(), "artifacts", "contracts", contractFile, `${contractName}.json`);
  if (!fs.existsSync(artifactPath)) {
    throw new Error(`Missing artifact for ${contractName}. Run npm run compile first.`);
  }

  return JSON.parse(fs.readFileSync(artifactPath, "utf8")) as ContractArtifact;
}

async function deployContract(
  wallet: ethers.Wallet,
  contractFile: string,
  contractName: string,
  constructorArgs: unknown[],
) {
  const artifact = loadArtifact(contractFile, contractName);
  const factory = new ethers.ContractFactory(artifact.abi, artifact.bytecode, wallet);
  const contract = await factory.deploy(...constructorArgs);
  await contract.waitForDeployment();
  return contract;
}

async function main() {
  const rpcUrl = process.env.SEPOLIA_RPC_URL || process.env.ALCHEMY_SEPOLIA_URL;
  const deployerKey = normalizePrivateKey(process.env.DEPLOYER_PRIVATE_KEY || process.env.PRIVATE_KEY);
  if (!rpcUrl || !deployerKey) {
    throw new Error("SEPOLIA_RPC_URL and DEPLOYER_PRIVATE_KEY are required.");
  }

  const provider = new ethers.JsonRpcProvider(rpcUrl);
  const deployer = new ethers.Wallet(deployerKey, provider);
  const network = await provider.getNetwork();

  const adminAddress = process.env.ADMIN_ADDRESS || deployer.address;
  const treasuryAddress = process.env.TREASURY_ADDRESS || deployer.address;
  const maxSupply = parseTokenAmount(process.env.EVFI_MAX_SUPPLY, "1000000000");
  const weeklyRewardPool = parseTokenAmount(process.env.WEEKLY_REWARD_POOL, "10000");
  const initialFunding = parseTokenAmount(process.env.INITIAL_REWARDS_FUNDING, "100000");

  console.log(`Deploying EvFi V2 contracts with ${deployer.address} on chain ${network.chainId}`);
  console.log(`Admin: ${adminAddress}`);
  console.log(`Treasury: ${treasuryAddress}`);

  const token = await deployContract(deployer, "EvFiToken.sol", "EvFiToken", [
    adminAddress,
    treasuryAddress,
    maxSupply,
  ]);
  const tokenAddress = await token.getAddress();
  console.log(`EvFiToken deployed to ${tokenAddress}`);

  const rewards = await deployContract(deployer, "EvFiRewards.sol", "EvFiRewards", [
    adminAddress,
    tokenAddress,
    weeklyRewardPool,
  ]);
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
    network: "sepolia",
    chainId: network.chainId.toString(),
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
  fs.writeFileSync(path.join(deploymentsDir, "sepolia.json"), JSON.stringify(deployment, null, 2));

  console.log("Deployment written to deployments/sepolia.json");
  console.log("Update .env with:");
  console.log(`EVFI_TOKEN_ADDRESS=${tokenAddress}`);
  console.log(`EVFI_REWARDS_ADDRESS=${rewardsAddress}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
