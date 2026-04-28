import { expect } from "chai";
import { network } from "hardhat";
import { anyValue } from "@nomicfoundation/hardhat-ethers-chai-matchers/withArgs";

const { ethers, networkHelpers } = await network.create();

describe("EVFIStaking", function () {
  async function deployFixture() {
    const [admin, treasury, user, outsider] = await ethers.getSigners();
    const maxSupply = ethers.parseUnits("1000000000", 18);
    const stakeAmount = ethers.parseUnits("100", 18);

    const token = await ethers.deployContract("EvFiToken", [admin.address, treasury.address, maxSupply]);
    await token.waitForDeployment();

    const feesPool = await ethers.deployContract("GeneratedFeesPool", [await token.getAddress(), admin.address]);
    await feesPool.waitForDeployment();

    const staking = await ethers.deployContract("EVFIStaking", [
      await token.getAddress(),
      await feesPool.getAddress(),
      admin.address,
      1000,
    ]);
    await staking.waitForDeployment();

    await token.connect(treasury).transfer(user.address, ethers.parseUnits("1000", 18));

    return {
      admin,
      treasury,
      user,
      outsider,
      token,
      feesPool,
      staking,
      stakeAmount,
    };
  }

  it("stakes EVFI into an allowed lock period and records the position", async function () {
    const { user, token, staking, stakeAmount } = await networkHelpers.loadFixture(deployFixture);

    await token.connect(user).approve(await staking.getAddress(), stakeAmount);

    await expect(staking.connect(user).stake(stakeAmount, 21600))
      .to.emit(staking, "Staked")
      .withArgs(user.address, 0n, stakeAmount, 21600n, anyValue);

    expect(await staking.totalStaked(user.address)).to.equal(stakeAmount);
    expect(await staking.getStakePositionsCount(user.address)).to.equal(1n);

    const position = await staking.getStakePosition(user.address, 0);
    expect(position.amount).to.equal(stakeAmount);
    expect(position.unlockTime).to.be.greaterThan(position.startTime);
  });

  it("routes the early unstake penalty to the generated fees pool", async function () {
    const { user, token, feesPool, staking, stakeAmount } = await networkHelpers.loadFixture(deployFixture);
    const penaltyAmount = ethers.parseUnits("10", 18);
    const returnedAmount = ethers.parseUnits("90", 18);

    await token.connect(user).approve(await staking.getAddress(), stakeAmount);
    await staking.connect(user).stake(stakeAmount, 86400);

    await expect(staking.connect(user).unstake(0, stakeAmount))
      .to.emit(staking, "Unstaked")
      .withArgs(user.address, 0n, stakeAmount, returnedAmount, penaltyAmount, true)
      .and.to.emit(feesPool, "FeesDeposited")
      .withArgs(await staking.getAddress(), penaltyAmount);

    expect(await staking.totalStaked(user.address)).to.equal(0n);
    expect(await token.balanceOf(await feesPool.getAddress())).to.equal(penaltyAmount);
    expect(await feesPool.tokenBalance()).to.equal(penaltyAmount);
  });

  it("does not apply a penalty after the lock expires", async function () {
    const { user, token, feesPool, staking, stakeAmount } = await networkHelpers.loadFixture(deployFixture);

    await token.connect(user).approve(await staking.getAddress(), stakeAmount);
    await staking.connect(user).stake(stakeAmount, 21600);
    await networkHelpers.time.increase(21601);

    await expect(staking.connect(user).unstake(0, stakeAmount))
      .to.emit(staking, "Unstaked")
      .withArgs(user.address, 0n, stakeAmount, stakeAmount, 0n, false);

    expect(await token.balanceOf(await feesPool.getAddress())).to.equal(0n);
  });

  it("lets only the owner change staking policy", async function () {
    const { admin, outsider, staking } = await networkHelpers.loadFixture(deployFixture);

    await expect(staking.connect(outsider).setEarlyUnstakePenaltyBps(500)).to.be.revertedWithCustomError(
      staking,
      "OwnableUnauthorizedAccount",
    );

    await expect(staking.connect(admin).setEarlyUnstakePenaltyBps(500))
      .to.emit(staking, "EarlyUnstakePenaltyUpdated")
      .withArgs(1000, 500);

    await expect(staking.connect(admin).setAllowedLockDuration(3600, true))
      .to.emit(staking, "LockDurationUpdated")
      .withArgs(3600, true);
  });

});
