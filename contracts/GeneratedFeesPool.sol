// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

contract GeneratedFeesPool is Ownable {
    using SafeERC20 for IERC20;

    IERC20 public immutable evfiToken;

    event FeesDeposited(address indexed from, uint256 amount);
    event FeesWithdrawn(address indexed to, uint256 amount);

    constructor(address token_, address initialOwner) Ownable(initialOwner) {
        require(token_ != address(0), "invalid token");
        evfiToken = IERC20(token_);
    }

    function notifyDeposit(uint256 amount) external {
        emit FeesDeposited(msg.sender, amount);
    }

    function withdraw(address to, uint256 amount) external onlyOwner {
        require(to != address(0), "invalid recipient");
        evfiToken.safeTransfer(to, amount);
        emit FeesWithdrawn(to, amount);
    }

    function tokenBalance() external view returns (uint256) {
        return evfiToken.balanceOf(address(this));
    }
}
