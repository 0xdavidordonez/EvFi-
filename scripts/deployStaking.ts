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

function requireAddress(value: string | undefined, name: string) {
  if (!value || !ethers.isAddress(value)) {
    throw new Error(`${name} must be a valid address.`);
  }
  return ethers.getAddress(value);
}

function parsePenaltyBps(value: string | undefined) {
  const parsed = Number.parseInt(value || "1000", 10);
  if (!Number.isInteger(parsed) || parsed < 0 || parsed > 10_000) {
    throw new Error("EARLY_UNSTAKE_PENALTY_BPS must be an integer from 0 to 10000.");
  }
  return parsed;
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

  const tokenAddress = requireAddress(process.env.EVFI_TOKEN_ADDRESS, "EVFI_TOKEN_ADDRESS");
  const provider = new ethers.JsonRpcProvider(rpcUrl);
  const deployer = new ethers.Wallet(deployerKey, provider);
  const network = await provider.getNetwork();
  if (network.chainId !== 11155111n) {
    throw new Error(`Refusing to deploy staking contracts to chain ${network.chainId}; expected Sepolia 11155111.`);
  }

  const initialOwner = requireAddress(process.env.ADMIN_ADDRESS || deployer.address, "ADMIN_ADDRESS");
  const penaltyBps = parsePenaltyBps(process.env.EARLY_UNSTAKE_PENALTY_BPS);

  console.log(`Deploying EVFI staking contracts with ${deployer.address} on Sepolia`);
  console.log(`EVFI token: ${tokenAddress}`);
  console.log(`Initial owner: ${initialOwner}`);
  console.log(`Early unstake penalty: ${penaltyBps} bps`);

  const generatedFeesPool = await deployContract(deployer, "GeneratedFeesPool.sol", "GeneratedFeesPool", [
    tokenAddress,
    initialOwner,
  ]);
  const generatedFeesPoolAddress = await generatedFeesPool.getAddress();
  console.log(`GeneratedFeesPool deployed to ${generatedFeesPoolAddress}`);

  const staking = await deployContract(deployer, "EVFIStaking.sol", "EVFIStaking", [
    tokenAddress,
    generatedFeesPoolAddress,
    initialOwner,
    penaltyBps,
  ]);
  const stakingAddress = await staking.getAddress();
  console.log(`EVFIStaking deployed to ${stakingAddress}`);

  const deployment = {
    network: "sepolia",
    chainId: network.chainId.toString(),
    deployer: deployer.address,
    initialOwner,
    tokenAddress,
    generatedFeesPoolAddress,
    stakingAddress,
    earlyUnstakePenaltyBps: penaltyBps,
    lockDurations: [21600, 86400, 604800],
    deployedAt: new Date().toISOString(),
  };

  const deploymentsDir = path.join(process.cwd(), "deployments");
  fs.mkdirSync(deploymentsDir, { recursive: true });
  fs.writeFileSync(path.join(deploymentsDir, "sepolia-staking.json"), JSON.stringify(deployment, null, 2));

  console.log("Deployment written to deployments/sepolia-staking.json");
  console.log("Update .env with:");
  console.log(`EVFI_TOKEN_ADDRESS=${tokenAddress}`);
  console.log(`GENERATED_FEES_POOL_ADDRESS=${generatedFeesPoolAddress}`);
  console.log(`EVFI_STAKING_CONTRACT_ADDRESS=${stakingAddress}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
