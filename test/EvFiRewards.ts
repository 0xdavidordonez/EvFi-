import { loadFixture } from "@nomicfoundation/hardhat-toolbox/network-helpers";
import { expect } from "chai";
import { ethers } from "hardhat";

describe("EvFi phase 1 contracts", function () {
  async function deployFixture() {
    const [admin, treasury, userOne, userTwo, outsider] = await ethers.getSigners();
    const maxSupply = ethers.parseUnits("1000000000", 18);
    const weeklyRewardPool = ethers.parseUnits("10000", 18);
    const initialFunding = ethers.parseUnits("250000", 18);

    const token = await ethers.deployContract("EvFiToken", [admin.address, treasury.address, maxSupply]);
    await token.waitForDeployment();

    const rewards = await ethers.deployContract("EvFiRewards", [
      admin.address,
      await token.getAddress(),
      weeklyRewardPool,
    ]);
    await rewards.waitForDeployment();

    await token.connect(treasury).transfer(await rewards.getAddress(), initialFunding);

    return {
      admin,
      treasury,
      userOne,
      userTwo,
      outsider,
      token,
      rewards,
      maxSupply,
      weeklyRewardPool,
      initialFunding,
    };
  }

  it("mints the fixed cap to treasury at deployment", async function () {
    const { token, treasury, maxSupply } = await loadFixture(deployFixture);

    expect(await token.totalSupply()).to.equal(maxSupply);
    expect(await token.balanceOf(treasury.address)).to.equal(maxSupply - ethers.parseUnits("250000", 18));
  });

  it("assigns and claims rewards from a funded pool", async function () {
    const { rewards, token, userOne } = await loadFixture(deployFixture);
    const rewardAmount = ethers.parseUnits("125", 18);

    await expect(rewards.assignRewards(userOne.address, rewardAmount, "week-1"))
      .to.emit(rewards, "RewardAssigned")
      .withArgs(userOne.address, rewardAmount, "week-1", rewardAmount);

    expect(await rewards.pendingRewards(userOne.address)).to.equal(rewardAmount);

    await expect(rewards.connect(userOne).claim())
      .to.emit(rewards, "RewardClaimed")
      .withArgs(userOne.address, rewardAmount);

    expect(await rewards.pendingRewards(userOne.address)).to.equal(0n);
    expect(await token.balanceOf(userOne.address)).to.equal(rewardAmount);
  });

  it("supports batched weekly reward assignments", async function () {
    const { rewards, userOne, userTwo } = await loadFixture(deployFixture);
    const rewardOne = ethers.parseUnits("40", 18);
    const rewardTwo = ethers.parseUnits("60", 18);

    await expect(
      rewards.assignRewardsBatch(
        [userOne.address, userTwo.address],
        [rewardOne, rewardTwo],
        "2026-W15",
      ),
    )
      .to.emit(rewards, "RewardsBatchAssigned")
      .withArgs("2026-W15", 2n, rewardOne + rewardTwo);

    expect(await rewards.pendingRewards(userOne.address)).to.equal(rewardOne);
    expect(await rewards.pendingRewards(userTwo.address)).to.equal(rewardTwo);
    expect(await rewards.totalPendingRewards()).to.equal(rewardOne + rewardTwo);
  });

  it("blocks assignments that exceed funded rewards balance", async function () {
    const { rewards, userOne, initialFunding } = await loadFixture(deployFixture);
    const tooMuch = initialFunding + 1n;

    await expect(rewards.assignRewards(userOne.address, tooMuch, "overflow")).to.be.revertedWithCustomError(
      rewards,
      "EvFiRewards__InsufficientFunding",
    );
  });

  it("restricts reward management to authorized accounts", async function () {
    const { rewards, outsider, userOne } = await loadFixture(deployFixture);

    await expect(
      rewards.connect(outsider).assignRewards(userOne.address, ethers.parseUnits("10", 18), "nope"),
    ).to.be.revertedWithCustomError(rewards, "AccessControlUnauthorizedAccount");
  });

  it("allows the admin to reconfigure the weekly pool", async function () {
    const { rewards, weeklyRewardPool } = await loadFixture(deployFixture);
    const newPool = weeklyRewardPool * 2n;

    await expect(rewards.setWeeklyRewardPool(newPool))
      .to.emit(rewards, "WeeklyRewardPoolUpdated")
      .withArgs(weeklyRewardPool, newPool);

    expect(await rewards.weeklyRewardPool()).to.equal(newPool);
  });
});
