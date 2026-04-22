import { expect } from "chai";
import { network } from "hardhat";

const { ethers, networkHelpers } = await network.create();

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

  it("mints initial circulating supply to treasury and preserves the fixed cap", async function () {
    const { token, treasury, maxSupply } = await networkHelpers.loadFixture(deployFixture);
    const initialTreasuryMint = maxSupply / 10n;

    expect(await token.totalSupply()).to.equal(initialTreasuryMint);
    expect(await token.balanceOf(treasury.address)).to.equal(initialTreasuryMint - ethers.parseUnits("250000", 18));
  });

  it("allows authorized airdrop minting up to the cap", async function () {
    const { token, admin, userOne } = await networkHelpers.loadFixture(deployFixture);
    const amount = ethers.parseUnits("123", 18);

    await token.connect(admin).mint(userOne.address, amount);

    expect(await token.balanceOf(userOne.address)).to.equal(amount);
  });

  it("assigns and claims rewards from a funded pool", async function () {
    const { rewards, token, userOne } = await networkHelpers.loadFixture(deployFixture);
    const rewardAmount = ethers.parseUnits("125", 18);

    await expect(rewards.assignRewards(userOne.address, rewardAmount, "week-1"))
      .to.emit(rewards, "RewardAssigned")
      .withArgs(userOne.address, rewardAmount, "week-1", rewardAmount);

    expect(await rewards.pendingRewards(userOne.address)).to.equal(rewardAmount);

    await expect(rewards.connect(userOne).claim())
      .to.emit(rewards, "RewardClaimed")
      .withArgs(userOne.address, rewardAmount);

    expect(await rewards.pendingRewards(userOne.address)).to.equal(0n);
    expect(await rewards.totalClaimed(userOne.address)).to.equal(rewardAmount);
    expect(await token.balanceOf(userOne.address)).to.equal(rewardAmount);
  });

  it("supports batched weekly reward assignments", async function () {
    const { rewards, userOne, userTwo } = await networkHelpers.loadFixture(deployFixture);
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
      .withArgs("2026-W15", 1n, 2n, rewardOne + rewardTwo);

    expect(await rewards.pendingRewards(userOne.address)).to.equal(rewardOne);
    expect(await rewards.pendingRewards(userTwo.address)).to.equal(rewardTwo);
    expect(await rewards.totalPendingRewards()).to.equal(rewardOne + rewardTwo);
    expect(await rewards.currentWeek()).to.equal(2n);
  });

  it("blocks batch assignments that exceed the weekly pool", async function () {
    const { rewards, userOne, weeklyRewardPool } = await networkHelpers.loadFixture(deployFixture);

    await expect(
      rewards.assignRewardsBatch([userOne.address], [weeklyRewardPool + 1n], "too-large"),
    ).to.be.revertedWithCustomError(rewards, "EvFiRewards__WeeklyPoolExceeded");
  });

  it("blocks assignments that exceed funded rewards balance", async function () {
    const { rewards, userOne, initialFunding } = await networkHelpers.loadFixture(deployFixture);
    const tooMuch = initialFunding + 1n;

    await rewards.setWeeklyRewardPool(tooMuch);

    await expect(rewards.assignRewards(userOne.address, tooMuch, "overflow")).to.be.revertedWithCustomError(
      rewards,
      "EvFiRewards__InsufficientFunding",
    );
  });

  it("restricts reward management to authorized accounts", async function () {
    const { rewards, outsider, userOne } = await networkHelpers.loadFixture(deployFixture);

    await expect(
      rewards.connect(outsider).assignRewards(userOne.address, ethers.parseUnits("10", 18), "nope"),
    ).to.be.revertedWithCustomError(rewards, "AccessControlUnauthorizedAccount");
  });

  it("allows the admin to reconfigure the weekly pool", async function () {
    const { rewards, weeklyRewardPool } = await networkHelpers.loadFixture(deployFixture);
    const newPool = weeklyRewardPool * 2n;

    await expect(rewards.setWeeklyRewardPool(newPool))
      .to.emit(rewards, "WeeklyRewardPoolUpdated")
      .withArgs(weeklyRewardPool, newPool);

    expect(await rewards.weeklyRewardPool()).to.equal(newPool);
  });
});
