(function () {
  const ETHERS_MISSING_MESSAGE = "Ethers library is not available. Onchain staking UI is loaded, but contract calls cannot run yet.";
  const STAKING_ABI = [
    "function stake(uint256 amount, uint64 lockDurationSeconds) returns (uint256 positionId)",
    "function unstake(uint256 positionId, uint256 amount)",
    "function totalStaked(address staker) view returns (uint256)",
    "function getStakePositionsCount(address staker) view returns (uint256)",
    "function getStakePosition(address staker, uint256 positionId) view returns (tuple(uint256 amount,uint64 startTime,uint64 unlockTime))",
    "function previewUnstake(address staker, uint256 positionId, uint256 amount) view returns (uint256 returnedAmount,uint256 penaltyAmount,bool early)",
    "function earlyUnstakePenaltyBps() view returns (uint16)",
  ];
  const ERC20_ABI = [
    "function allowance(address owner, address spender) view returns (uint256)",
    "function approve(address spender, uint256 amount) returns (bool)",
  ];

  function formatEvfi(value) {
    const numeric = Number(value || 0);
    if (!Number.isFinite(numeric)) {
      return "0.00";
    }
    return numeric.toFixed(2);
  }

  function formatDuration(seconds) {
    const value = Number(seconds || 0);
    if (value % 604800 === 0) return `${value / 604800}w`;
    if (value % 86400 === 0) return `${value / 86400}d`;
    if (value % 3600 === 0) return `${value / 3600}h`;
    return `${value}s`;
  }

  function deriveTier(totalStaked, thresholds) {
    const total = Number(totalStaked || 0);
    return (thresholds || []).reduce((selected, threshold) => {
      const minimumAmount = Number(threshold.minimumAmount || 0);
      if (total + 1e-9 >= minimumAmount) {
        return threshold;
      }
      return selected;
    }, null);
  }

  function mergeState(backendState, chainState) {
    if (!chainState || chainState.source !== "wallet-chain") {
      return backendState || {};
    }
    if (!backendState || backendState.source !== "onchain" || Number(backendState.totalStaked || 0) !== Number(chainState.totalStaked || 0)) {
      return { ...(backendState || {}), ...chainState };
    }
    return backendState;
  }

  function toHexChainId(chainId) {
    return `0x${Number(chainId || 0).toString(16)}`;
  }

  async function ensureSepolia(chainId) {
    if (!window.ethereum) {
      throw new Error("MetaMask is required for staking.");
    }
    const currentChainId = await window.ethereum.request({ method: "eth_chainId" });
    const expectedChainId = toHexChainId(chainId);
    if ((currentChainId || "").toLowerCase() === expectedChainId.toLowerCase()) {
      return;
    }
    try {
      await window.ethereum.request({
        method: "wallet_switchEthereumChain",
        params: [{ chainId: expectedChainId }],
      });
    } catch (error) {
      throw new Error("Switch MetaMask to Sepolia before staking.");
    }
  }

  async function getConnectedWallet() {
    if (!window.ethereum) {
      return "";
    }
    const accounts = await window.ethereum.request({ method: "eth_accounts" });
    return (accounts && accounts[0]) || "";
  }

  async function getOrRequestWallet() {
    if (!window.ethereum) {
      throw new Error("MetaMask is required for staking.");
    }
    const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
    return (accounts && accounts[0]) || "";
  }

  async function fetchJson(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || `Request failed: ${response.status}`);
    }
    return payload;
  }

  async function postAudit(action, wallet, amount, txHash, extra) {
    try {
      await fetchJson("/api/staking/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          wallet,
          amount,
          txHash,
          ...(extra || {}),
        }),
      });
    } catch (error) {
      console.warn("Failed to mirror onchain staking action", error);
    }
  }

  function createPanel() {
    const panel = document.createElement("section");
    panel.id = "onchain-staking-panel";
    panel.className = "onchain-staking-card";
    panel.innerHTML = `
      <div class="staking-panel-header">
        <div>
          <h3>Onchain EVFi Staking</h3>
          <p>Sepolia staking with real wallet approvals, lock periods, and early-unstake penalty routing.</p>
        </div>
        <button id="refreshOnchainStakingButton" class="staking-refresh-button" type="button">Refresh</button>
      </div>
      <div id="onchainStakingStatus" class="staking-status" style="margin-top:12px;"></div>
      <div id="onchainStakingSummary"></div>
      <div id="onchainStakingForm" class="staking-form">
        <label>
          <span>Amount (EVFi)</span>
          <input id="onchainStakeAmount" type="number" min="0" step="0.01" placeholder="100" />
        </label>
        <label>
          <span>Lock Period</span>
          <select id="onchainStakeLock"></select>
        </label>
        <button id="stakeOnchainButton" class="stake-onchain-button" type="button">Approve + Stake</button>
      </div>
      <div id="onchainStakePositions" style="margin-top:16px;"></div>
    `;
    return panel;
  }

  function findMountTarget() {
    return document.getElementById("onchainStakingMount");
  }

  function disableLegacyStakeButtons() {
    document.querySelectorAll('.utility-action-button[data-action-type="stake"]').forEach((button) => {
      button.disabled = true;
      button.title = "Legacy app-level staking is disabled. Use the onchain staking panel below.";
    });
    const unstakeButton = document.getElementById("unstakeUtilityButton");
    if (unstakeButton) {
      unstakeButton.disabled = true;
      unstakeButton.title = "Legacy app-level unstaking is disabled. Use the onchain staking panel below.";
    }
  }

  async function init() {
    disableLegacyStakeButtons();

    const mountTarget = findMountTarget();
    if (!mountTarget) {
      return;
    }

    const config = await fetchJson("/api/staking/config");
    if (!config || config.mode !== "onchain") {
      return;
    }

    const panel = createPanel();
    mountTarget.appendChild(panel);

    const statusEl = document.getElementById("onchainStakingStatus");
    const summaryEl = document.getElementById("onchainStakingSummary");
    const lockSelect = document.getElementById("onchainStakeLock");
    const amountInput = document.getElementById("onchainStakeAmount");
    const positionsEl = document.getElementById("onchainStakePositions");
    const refreshButton = document.getElementById("refreshOnchainStakingButton");
    const stakeButton = document.getElementById("stakeOnchainButton");

    (config.lockOptions || []).forEach((seconds) => {
      const option = document.createElement("option");
      option.value = String(seconds);
      option.textContent = formatDuration(seconds);
      lockSelect.appendChild(option);
    });

    if (!config.enabled || !config.stakingContractAddress || !config.tokenAddress) {
      statusEl.textContent = "Configure EVFi token and staking contract addresses to enable onchain staking.";
      stakeButton.disabled = true;
      return;
    }

    if (!window.ethereum) {
      statusEl.textContent = "MetaMask not detected. Install or open the dashboard in MetaMask to use onchain staking.";
      stakeButton.disabled = true;
      return;
    }

    if (!window.ethers) {
      statusEl.textContent = ETHERS_MISSING_MESSAGE;
      stakeButton.disabled = true;
      return;
    }

    async function readWalletChainState(wallet) {
      const provider = new window.ethers.BrowserProvider(window.ethereum);
      const staking = new window.ethers.Contract(config.stakingContractAddress, STAKING_ABI, provider);
      const decimals = Number(config.tokenDecimals || 18);
      const totalStakedRaw = await staking.totalStaked(wallet);
      const positionCount = Number(await staking.getStakePositionsCount(wallet));
      const penaltyBps = Number(await staking.earlyUnstakePenaltyBps());
      const positions = [];
      for (let positionId = 0; positionId < positionCount; positionId += 1) {
        const position = await staking.getStakePosition(wallet, positionId);
        const amountRaw = position.amount ?? position[0];
        if (amountRaw <= 0n) {
          continue;
        }
        const preview = await staking.previewUnstake(wallet, positionId, amountRaw);
        const amount = Number(window.ethers.formatUnits(amountRaw, decimals));
        positions.push({
          positionId,
          amount,
          startTime: Number(position.startTime ?? position[1]),
          unlockTime: Number(position.unlockTime ?? position[2]),
          early: Boolean(preview.early ?? preview[2]),
          returnedAmount: Number(window.ethers.formatUnits(preview.returnedAmount ?? preview[0], decimals)),
          penaltyAmount: Number(window.ethers.formatUnits(preview.penaltyAmount ?? preview[1], decimals)),
        });
      }
      const totalStaked = Number(window.ethers.formatUnits(totalStakedRaw, decimals));
      const activeTier = deriveTier(totalStaked, config.thresholds);
      return {
        source: "wallet-chain",
        enabled: true,
        totalStaked,
        positionCount,
        penaltyBps,
        positions,
        activeStake: activeTier ? {
          stakeTier: activeTier.label,
          tierKey: String(activeTier.label || "").toLowerCase(),
          evfiAmount: totalStaked,
          stakeEvfi: totalStaked,
          boostPct: Number(activeTier.boostPct || 0),
          rewardBoostPct: Number(activeTier.boostPct || 0),
        } : null,
      };
    }

    async function refreshState() {
      const wallet = await getConnectedWallet();
      if (!wallet) {
        statusEl.textContent = "Connect your wallet to view onchain staking positions.";
        summaryEl.innerHTML = "";
        positionsEl.innerHTML = "";
        return;
      }

      try {
        await ensureSepolia(config.chainId);
      } catch (error) {
        statusEl.textContent = error.message || "Switch MetaMask to Sepolia.";
        summaryEl.innerHTML = "";
        positionsEl.innerHTML = "";
        return;
      }

      statusEl.textContent = `Wallet ${wallet} connected on Sepolia staking mode.`;
      let backendState = {};
      try {
        backendState = await fetchJson(`/api/staking/state?wallet=${encodeURIComponent(wallet)}`);
      } catch (error) {
        backendState = { source: `backend-error:${error.message || "unknown"}` };
      }
      let chainState = null;
      try {
        chainState = await readWalletChainState(wallet);
      } catch (error) {
        console.warn("Failed to read staking state from wallet provider", error);
      }
      const state = mergeState(backendState, chainState);
      const activeStake = state.activeStake || null;
      const sourceLabel = state.source === "wallet-chain" ? "wallet chain read" : "backend chain read";
      summaryEl.innerHTML = `
        <div class="staking-summary-grid">
          <div class="staking-summary-stat"><strong>Total Staked</strong><div>${formatEvfi(state.totalStaked)} EVFi</div></div>
          <div class="staking-summary-stat"><strong>Penalty</strong><div>${Number(state.penaltyBps || 0) / 100}% early-unstake fee</div></div>
          <div class="staking-summary-stat"><strong>Stake Tier</strong><div>${activeStake ? activeStake.stakeTier : "None"}</div></div>
          <div class="staking-summary-stat"><strong>Boost</strong><div>${activeStake ? formatEvfi(activeStake.boostPct) : "0.00"}%</div></div>
        </div>
        <div class="staking-source">State source: ${sourceLabel}</div>
      `;

      if (!state.positions || !state.positions.length) {
        positionsEl.innerHTML = "<p style='opacity:.8;'>No onchain stake positions yet.</p>";
        return;
      }

      positionsEl.innerHTML = state.positions.map((position) => `
        <div class="staking-position-card">
          <div><strong>Position #${position.positionId}</strong></div>
          <div>${formatEvfi(position.amount)} EVFi locked until ${new Date(position.unlockTime * 1000).toLocaleString()}</div>
          <div>${position.early ? `Unstaking now returns ${formatEvfi(position.returnedAmount)} EVFi and sends ${formatEvfi(position.penaltyAmount)} EVFi to generated_fees.` : "No early-unstake penalty applies."}</div>
          <button type="button" class="onchain-unstake-button" data-position-id="${position.positionId}" data-amount="${position.amount}">Unstake Position</button>
        </div>
      `).join("");

      positionsEl.querySelectorAll(".onchain-unstake-button").forEach((button) => {
        button.addEventListener("click", async () => {
          const walletAddress = await getOrRequestWallet();
          await ensureSepolia(config.chainId);
          const provider = new window.ethers.BrowserProvider(window.ethereum);
          const signer = await provider.getSigner();
          const staking = new window.ethers.Contract(config.stakingContractAddress, STAKING_ABI, signer);
          const amountValue = button.getAttribute("data-amount") || "0";
          const amountWei = window.ethers.parseUnits(amountValue, Number(config.tokenDecimals || 18));
          button.disabled = true;
          try {
            statusEl.textContent = "Submitting unstake transaction in MetaMask...";
            const tx = await staking.unstake(Number(button.getAttribute("data-position-id")), amountWei);
            await tx.wait();
            await postAudit("unstake", walletAddress, amountValue, tx.hash, {
              positionId: Number(button.getAttribute("data-position-id")),
            });
            statusEl.textContent = `Unstake confirmed for ${walletAddress}. Refreshing...`;
            window.location.reload();
          } catch (error) {
            button.disabled = false;
            statusEl.textContent = error && error.message ? error.message : "Unstake failed.";
          }
        });
      });
    }

    refreshButton.addEventListener("click", refreshState);

    stakeButton.addEventListener("click", async () => {
      const amountValue = amountInput.value.trim();
      const lockSeconds = Number(lockSelect.value || 0);
      const amountNumber = Number(amountValue);
      if (!amountValue || !Number.isFinite(amountNumber) || amountNumber <= 0) {
        statusEl.textContent = "Enter a valid EVFi staking amount.";
        return;
      }
      try {
        const wallet = await getOrRequestWallet();
        await ensureSepolia(config.chainId);
        const provider = new window.ethers.BrowserProvider(window.ethereum);
        const signer = await provider.getSigner();
        const token = new window.ethers.Contract(config.tokenAddress, ERC20_ABI, signer);
        const staking = new window.ethers.Contract(config.stakingContractAddress, STAKING_ABI, signer);
        const amountWei = window.ethers.parseUnits(amountValue, Number(config.tokenDecimals || 18));
        const allowance = await token.allowance(wallet, config.stakingContractAddress);

        stakeButton.disabled = true;
        if (allowance < amountWei) {
          statusEl.textContent = "Submitting EVFi approve transaction in MetaMask...";
          const approveTx = await token.approve(config.stakingContractAddress, amountWei);
          await approveTx.wait();
        }

        statusEl.textContent = "Submitting stake transaction in MetaMask...";
        const stakeTx = await staking.stake(amountWei, lockSeconds);
        await stakeTx.wait();
        await postAudit("stake", wallet, amountValue, stakeTx.hash, {
          lockSeconds,
        });
        statusEl.textContent = "Stake confirmed. Reloading dashboard...";
        window.location.reload();
      } catch (error) {
        stakeButton.disabled = false;
        statusEl.textContent = error && error.message ? error.message : "Stake failed.";
      }
    });

    window.ethereum.on && window.ethereum.on("accountsChanged", refreshState);
    window.ethereum.on && window.ethereum.on("chainChanged", refreshState);
    window.addEventListener("evfi:prefillStake", (event) => {
      const amount = event.detail && event.detail.amount;
      if (amountInput && amount) {
        amountInput.value = String(amount);
        amountInput.focus();
        panel.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
    await refreshState();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
