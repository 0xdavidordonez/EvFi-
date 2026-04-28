// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

interface IGeneratedFeesPool {
    function notifyDeposit(uint256 amount) external;
}

contract EVFIStaking is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    struct StakePosition {
        uint256 amount;
        uint64 startTime;
        uint64 unlockTime;
    }

    IERC20 public immutable evfiToken;
    address public generatedFeesPool;
    uint16 public earlyUnstakePenaltyBps;

    mapping(address => StakePosition[]) private stakePositions;
    mapping(address => uint256) public totalStaked;
    mapping(uint64 => bool) public allowedLockDurations;

    event Staked(
        address indexed staker,
        uint256 indexed positionId,
        uint256 amount,
        uint64 lockDuration,
        uint64 unlockTime
    );
    event Unstaked(
        address indexed staker,
        uint256 indexed positionId,
        uint256 grossAmount,
        uint256 returnedAmount,
        uint256 penaltyAmount,
        bool early
    );
    event GeneratedFeesPoolUpdated(address indexed previousPool, address indexed newPool);
    event EarlyUnstakePenaltyUpdated(uint16 previousPenaltyBps, uint16 newPenaltyBps);
    event LockDurationUpdated(uint64 indexed durationSeconds, bool allowed);

    constructor(
        address token_,
        address generatedFeesPool_,
        address initialOwner,
        uint16 earlyUnstakePenaltyBps_
    ) Ownable(initialOwner) {
        require(token_ != address(0), "invalid token");
        require(generatedFeesPool_ != address(0), "invalid fees pool");
        require(earlyUnstakePenaltyBps_ <= 10_000, "invalid penalty");

        evfiToken = IERC20(token_);
        generatedFeesPool = generatedFeesPool_;
        earlyUnstakePenaltyBps = earlyUnstakePenaltyBps_;

        allowedLockDurations[6 hours] = true;
        allowedLockDurations[1 days] = true;
        allowedLockDurations[7 days] = true;
    }

    function stake(uint256 amount, uint64 lockDurationSeconds) external nonReentrant returns (uint256 positionId) {
        require(amount > 0, "invalid amount");
        require(allowedLockDurations[lockDurationSeconds], "unsupported lock");

        evfiToken.safeTransferFrom(msg.sender, address(this), amount);

        positionId = stakePositions[msg.sender].length;
        uint64 startTime = uint64(block.timestamp);
        uint64 unlockTime = startTime + lockDurationSeconds;

        stakePositions[msg.sender].push(
            StakePosition({
                amount: amount,
                startTime: startTime,
                unlockTime: unlockTime
            })
        );
        totalStaked[msg.sender] += amount;

        emit Staked(msg.sender, positionId, amount, lockDurationSeconds, unlockTime);
    }

    function unstake(uint256 positionId, uint256 amount) external nonReentrant {
        require(positionId < stakePositions[msg.sender].length, "invalid position");
        require(amount > 0, "invalid amount");

        StakePosition storage position = stakePositions[msg.sender][positionId];
        require(position.amount >= amount, "insufficient staked");

        bool early = block.timestamp < position.unlockTime;
        uint256 penaltyAmount = early ? (amount * earlyUnstakePenaltyBps) / 10_000 : 0;
        uint256 returnedAmount = amount - penaltyAmount;

        position.amount -= amount;
        totalStaked[msg.sender] -= amount;

        if (penaltyAmount > 0) {
            evfiToken.safeTransfer(generatedFeesPool, penaltyAmount);
            IGeneratedFeesPool(generatedFeesPool).notifyDeposit(penaltyAmount);
        }
        evfiToken.safeTransfer(msg.sender, returnedAmount);

        emit Unstaked(msg.sender, positionId, amount, returnedAmount, penaltyAmount, early);
    }

    function getStakePositionsCount(address staker) external view returns (uint256) {
        return stakePositions[staker].length;
    }

    function getStakePosition(address staker, uint256 positionId) external view returns (StakePosition memory) {
        require(positionId < stakePositions[staker].length, "invalid position");
        return stakePositions[staker][positionId];
    }

    function previewUnstake(address staker, uint256 positionId, uint256 amount)
        external
        view
        returns (uint256 returnedAmount, uint256 penaltyAmount, bool early)
    {
        require(positionId < stakePositions[staker].length, "invalid position");
        StakePosition storage position = stakePositions[staker][positionId];
        require(position.amount >= amount, "insufficient staked");

        early = block.timestamp < position.unlockTime;
        penaltyAmount = early ? (amount * earlyUnstakePenaltyBps) / 10_000 : 0;
        returnedAmount = amount - penaltyAmount;
    }

    function setGeneratedFeesPool(address newGeneratedFeesPool) external onlyOwner {
        require(newGeneratedFeesPool != address(0), "invalid fees pool");
        address previousPool = generatedFeesPool;
        generatedFeesPool = newGeneratedFeesPool;
        emit GeneratedFeesPoolUpdated(previousPool, newGeneratedFeesPool);
    }

    function setEarlyUnstakePenaltyBps(uint16 newPenaltyBps) external onlyOwner {
        require(newPenaltyBps <= 10_000, "invalid penalty");
        uint16 previousPenaltyBps = earlyUnstakePenaltyBps;
        earlyUnstakePenaltyBps = newPenaltyBps;
        emit EarlyUnstakePenaltyUpdated(previousPenaltyBps, newPenaltyBps);
    }

    function setAllowedLockDuration(uint64 durationSeconds, bool allowed) external onlyOwner {
        allowedLockDurations[durationSeconds] = allowed;
        emit LockDurationUpdated(durationSeconds, allowed);
    }
}
