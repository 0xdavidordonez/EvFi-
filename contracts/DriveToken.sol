// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @dev Legacy prototype contract retained for reference only.
/// @dev Phase 1 Sepolia integration uses EvFiToken.sol and EvFiRewards.sol instead.

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Burnable.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";

contract DriveToken is ERC20, ERC20Burnable, AccessControl, ERC20Permit {

    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");
    uint256 public constant MAX_SUPPLY = 1_000_000_000 * 10 ** 18;
    uint256 public tokensPerMile = 1 * 10 ** 18;

    event TripRewarded(address indexed driver, uint256 miles, uint256 tokensEarned, string tripId);
    event RewardRateUpdated(uint256 oldRate, uint256 newRate);

    constructor(address defaultAdmin)
        ERC20("DriveToken", "DRV")
        ERC20Permit("DriveToken")
    {
        _grantRole(DEFAULT_ADMIN_ROLE, defaultAdmin);
        _grantRole(MINTER_ROLE, defaultAdmin);
    }

    function rewardTrip(address driver, uint256 miles, string calldata tripId) external onlyRole(MINTER_ROLE) {
        uint256 tokensEarned = (miles * tokensPerMile) / 100;
        require(totalSupply() + tokensEarned <= MAX_SUPPLY, "DriveToken: max supply exceeded");
        _mint(driver, tokensEarned);
        emit TripRewarded(driver, miles, tokensEarned, tripId);
    }

    function mint(address to, uint256 amount) external onlyRole(MINTER_ROLE) {
        require(totalSupply() + amount <= MAX_SUPPLY, "DriveToken: max supply exceeded");
        _mint(to, amount);
    }

    function setTokensPerMile(uint256 newRate) external onlyRole(DEFAULT_ADMIN_ROLE) {
        emit RewardRateUpdated(tokensPerMile, newRate);
        tokensPerMile = newRate;
    }

    function addMinter(address minter) external onlyRole(DEFAULT_ADMIN_ROLE) {
        _grantRole(MINTER_ROLE, minter);
    }

    function removeMinter(address minter) external onlyRole(DEFAULT_ADMIN_ROLE) {
        _revokeRole(MINTER_ROLE, minter);
    }
}
