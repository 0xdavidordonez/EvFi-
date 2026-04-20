// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Burnable.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Capped.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";

contract EvFiToken is ERC20, ERC20Burnable, ERC20Capped, ERC20Permit, AccessControl {
    bytes32 public constant TREASURY_ROLE = keccak256("TREASURY_ROLE");
    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");

    error EvFiToken__InvalidAddress();
    error EvFiToken__InvalidCap();

    constructor(address admin, address treasury, uint256 maxSupply)
        ERC20("Electrified Vehicle Finance", "EVFI")
        ERC20Permit("Electrified Vehicle Finance")
        ERC20Capped(maxSupply)
    {
        if (admin == address(0) || treasury == address(0)) {
            revert EvFiToken__InvalidAddress();
        }
        if (maxSupply == 0) {
            revert EvFiToken__InvalidCap();
        }

        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(TREASURY_ROLE, treasury);
        _grantRole(MINTER_ROLE, admin);
        _mint(treasury, maxSupply / 10);
    }

    function supportsInterface(bytes4 interfaceId) public view override(AccessControl) returns (bool) {
        return super.supportsInterface(interfaceId);
    }

    function mint(address to, uint256 amount) external onlyRole(MINTER_ROLE) {
        if (to == address(0)) {
            revert EvFiToken__InvalidAddress();
        }
        _mint(to, amount);
    }

    function _update(address from, address to, uint256 value) internal override(ERC20, ERC20Capped) {
        super._update(from, to, value);
    }
}
