// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

contract EvFiRewards is AccessControl, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    bytes32 public constant REWARD_MANAGER_ROLE = keccak256("REWARD_MANAGER_ROLE");

    IERC20 public immutable rewardToken;
    uint256 public weeklyRewardPool;
    uint256 public currentWeek;
    uint256 public totalPendingRewards;
    mapping(address => uint256) public pendingRewards;
    mapping(address => uint256) public totalClaimed;

    error EvFiRewards__InvalidAddress();
    error EvFiRewards__InvalidArrayLength();
    error EvFiRewards__InvalidAmount();
    error EvFiRewards__NoRewards();
    error EvFiRewards__InsufficientFunding(uint256 contractBalance, uint256 requiredBalance);
    error EvFiRewards__WeeklyPoolExceeded(uint256 requested, uint256 weeklyPool);

    event WeeklyRewardPoolUpdated(uint256 previousPool, uint256 newPool);
    event RewardAssigned(address indexed account, uint256 amount, string reason, uint256 pendingTotal);
    event RewardsBatchAssigned(string indexed batchId, uint256 indexed week, uint256 recipients, uint256 totalAmount);
    event RewardClaimed(address indexed account, uint256 amount);
    event UnallocatedTokensRescued(address indexed to, uint256 amount);

    constructor(address admin, address tokenAddress, uint256 initialWeeklyRewardPool) {
        if (admin == address(0) || tokenAddress == address(0)) {
            revert EvFiRewards__InvalidAddress();
        }

        rewardToken = IERC20(tokenAddress);
        weeklyRewardPool = initialWeeklyRewardPool;
        currentWeek = 1;

        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(REWARD_MANAGER_ROLE, admin);
    }

    function assignRewards(address account, uint256 amount, string calldata reason)
        external
        onlyRole(REWARD_MANAGER_ROLE)
        whenNotPaused
    {
        _assignReward(account, amount, reason);
    }

    function assignRewardsBatch(address[] calldata accounts, uint256[] calldata amounts, string calldata batchId)
        external
        onlyRole(REWARD_MANAGER_ROLE)
        whenNotPaused
    {
        if (accounts.length == 0 || accounts.length != amounts.length) {
            revert EvFiRewards__InvalidArrayLength();
        }

        uint256 totalAmount;
        for (uint256 i = 0; i < amounts.length; i++) {
            if (accounts[i] == address(0) || amounts[i] == 0) {
                revert EvFiRewards__InvalidAmount();
            }
            totalAmount += amounts[i];
        }

        _ensureFunded(totalAmount);
        if (totalAmount > weeklyRewardPool) {
            revert EvFiRewards__WeeklyPoolExceeded(totalAmount, weeklyRewardPool);
        }

        for (uint256 i = 0; i < accounts.length; i++) {
            pendingRewards[accounts[i]] += amounts[i];
            emit RewardAssigned(accounts[i], amounts[i], batchId, pendingRewards[accounts[i]]);
        }

        totalPendingRewards += totalAmount;
        emit RewardsBatchAssigned(batchId, currentWeek, accounts.length, totalAmount);
        currentWeek += 1;
    }

    function claim() external nonReentrant whenNotPaused {
        uint256 amount = pendingRewards[msg.sender];
        if (amount == 0) {
            revert EvFiRewards__NoRewards();
        }

        pendingRewards[msg.sender] = 0;
        totalPendingRewards -= amount;
        totalClaimed[msg.sender] += amount;
        rewardToken.safeTransfer(msg.sender, amount);

        emit RewardClaimed(msg.sender, amount);
    }

    function setWeeklyRewardPool(uint256 newWeeklyRewardPool) external onlyRole(DEFAULT_ADMIN_ROLE) {
        emit WeeklyRewardPoolUpdated(weeklyRewardPool, newWeeklyRewardPool);
        weeklyRewardPool = newWeeklyRewardPool;
    }

    function pause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _unpause();
    }

    function rescueUnallocatedTokens(address to, uint256 amount) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (to == address(0)) {
            revert EvFiRewards__InvalidAddress();
        }
        if (amount == 0) {
            revert EvFiRewards__InvalidAmount();
        }
        if (availableRewardsBalance() < amount) {
            revert EvFiRewards__InsufficientFunding(rewardToken.balanceOf(address(this)), totalPendingRewards + amount);
        }

        rewardToken.safeTransfer(to, amount);
        emit UnallocatedTokensRescued(to, amount);
    }

    function availableRewardsBalance() public view returns (uint256) {
        uint256 balance = rewardToken.balanceOf(address(this));
        return balance > totalPendingRewards ? balance - totalPendingRewards : 0;
    }

    function _assignReward(address account, uint256 amount, string calldata reason) private {
        if (account == address(0)) {
            revert EvFiRewards__InvalidAddress();
        }
        if (amount == 0) {
            revert EvFiRewards__InvalidAmount();
        }
        if (amount > weeklyRewardPool) {
            revert EvFiRewards__WeeklyPoolExceeded(amount, weeklyRewardPool);
        }

        _ensureFunded(amount);
        pendingRewards[account] += amount;
        totalPendingRewards += amount;

        emit RewardAssigned(account, amount, reason, pendingRewards[account]);
    }

    function _ensureFunded(uint256 amountToReserve) private view {
        uint256 currentBalance = rewardToken.balanceOf(address(this));
        uint256 requiredBalance = totalPendingRewards + amountToReserve;
        if (currentBalance < requiredBalance) {
            revert EvFiRewards__InsufficientFunding(currentBalance, requiredBalance);
        }
    }
}
