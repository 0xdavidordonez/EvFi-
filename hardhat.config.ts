import { HardhatUserConfig } from "hardhat/config";
import * as dotenv from "dotenv";
dotenv.config();

function normalizePrivateKey(value?: string) {
  if (!value) {
    return undefined;
  }

  return value.startsWith("0x") ? value : `0x${value}`;
}

const sepoliaUrl = process.env.SEPOLIA_RPC_URL || process.env.ALCHEMY_SEPOLIA_URL || "";
const deployerKey = normalizePrivateKey(process.env.DEPLOYER_PRIVATE_KEY || process.env.PRIVATE_KEY);

const config: HardhatUserConfig = {
  solidity: {
    version: "0.8.28",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200,
      },
      evmVersion: "cancun",
    },
  },
  networks: {
    ...(sepoliaUrl
        ? {
          sepolia: {
            type: "http",
            url: sepoliaUrl,
            accounts: deployerKey ? [deployerKey] : [],
          },
        }
      : {}),
  },
  etherscan: {
    apiKey: process.env.ETHERSCAN_API_KEY || "",
  },
};

export default config;
