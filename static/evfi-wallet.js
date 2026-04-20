(function () {
  const cfg = window.EVFI_WEB3_CONFIG || {};
  const els = {
    connect: document.getElementById("connectWalletButton"),
    connectLabel: document.getElementById("connectWalletButtonLabel"),
    disconnect: document.getElementById("disconnectWalletButton"),
    walletAddress: document.getElementById("walletAddressText"),
    status: document.getElementById("web3StatusText"),
    badge: document.getElementById("walletConnectionBadge"),
    toast: document.getElementById("walletToast"),
    hint: document.getElementById("walletConnectHint"),
    walletExplorer: document.getElementById("walletExplorerLink"),
    tokenExplorer: document.getElementById("tokenExplorerLink"),
    rewardsExplorer: document.getElementById("rewardsExplorerLink"),
    txExplorer: document.getElementById("txExplorerLink"),
    claimable: document.getElementById("claimableRewardsValue"),
    balance: document.getElementById("walletBalanceValue"),
    claim: document.getElementById("claimRewardsButton"),
    claimAirdrop: document.getElementById("claimAirdropButton"),
    assign: document.getElementById("assignRewardsButton"),
    refreshAndDistribute: document.getElementById("refreshAndDistributeButton"),
    sportMode: document.getElementById("sportModeButton"),
    sportModeStatus: document.getElementById("sportModeStatus"),
    adminKey: document.getElementById("adminKeyInput"),
    distributionRecipient: document.getElementById("distributionRecipientInput"),
  };

  if (!els.connect) {
    return;
  }

  const state = {
    provider: null,
    signer: null,
    address: cfg.defaultWalletAddress || "",
    toastTimer: null,
    connectState: "idle",
  };

  const tokenAbi = [
    "function balanceOf(address) view returns (uint256)",
  ];

  const rewardsAbi = [
    "function pendingRewards(address) view returns (uint256)",
    "function claim()",
  ];

  function stringifyExtraError(payload) {
    const parts = [];
    if (payload?.code) {
      parts.push(`code: ${payload.code}`);
    }
    if (payload?.reason) {
      parts.push(`reason: ${payload.reason}`);
    }
    if (payload?.stack) {
      parts.push(`stack: ${payload.stack}`);
    }
    return parts.join(" | ");
  }

  function setBadgeState(nextState) {
    const normalized = nextState || "idle";
    state.connectState = normalized;

    if (els.badge) {
      els.badge.dataset.state = normalized;
      els.badge.textContent =
        normalized === "connecting"
          ? "Connecting"
          : normalized === "connected"
            ? "Connected"
            : normalized === "error"
              ? "Attention"
              : "Not Connected";
    }

    if (els.connect) {
      els.connect.dataset.state = normalized;
      els.connect.disabled = normalized === "connecting";
    }

    if (els.connectLabel) {
      els.connectLabel.textContent =
        normalized === "connecting"
          ? "Connecting to Wallet..."
          : normalized === "connected"
            ? "Wallet Connected"
            : "Connect Sepolia Wallet";
    }

    if (els.disconnect) {
      els.disconnect.classList.toggle("is-hidden", normalized !== "connected");
    }
  }

  function setStatus(message, isError) {
    if (!els.status) {
      return;
    }

    els.status.textContent = message;
    els.status.style.color = isError ? "#ff9aa7" : "#9ca3af";
    setBadgeState(isError ? "error" : state.connectState === "connected" ? "connected" : "idle");
  }

  function setHint(message) {
    if (els.hint) {
      els.hint.textContent = message;
    }
  }

  function showToast(message, tone) {
    if (!els.toast) {
      return;
    }

    if (state.toastTimer) {
      window.clearTimeout(state.toastTimer);
    }

    els.toast.textContent = message;
    els.toast.dataset.tone = tone || "success";
    els.toast.classList.add("is-visible");
    state.toastTimer = window.setTimeout(() => {
      els.toast.classList.remove("is-visible");
    }, 2600);
  }

  function formatToken(value) {
    return Number(ethers.formatUnits(value, 18)).toLocaleString(undefined, {
      maximumFractionDigits: 2,
    });
  }

  function formatNumber(value) {
    return Number(value || 0).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function updateWalletAddress(value) {
    if (!els.walletAddress) {
      return;
    }

    els.walletAddress.textContent = value || "Wallet not connected";
  }

  function syncRecipientInput(value) {
    if (els.distributionRecipient) {
      els.distributionRecipient.value = value || cfg.defaultWalletAddress || "";
    }
  }

  function getRecipientWallet() {
    return els.distributionRecipient?.value?.trim() || state.address || cfg.defaultWalletAddress;
  }

  function setExplorerHref(el, value) {
    if (!el || !value) {
      return;
    }

    el.href = `https://sepolia.etherscan.io/address/${value}`;
    el.classList.remove("is-hidden");
  }

  function setTxExplorer(hash) {
    if (!els.txExplorer) {
      return;
    }

    if (!hash) {
      els.txExplorer.href = "#";
      els.txExplorer.classList.add("is-hidden");
      return;
    }

    els.txExplorer.href = `https://sepolia.etherscan.io/tx/${hash}`;
    els.txExplorer.classList.remove("is-hidden");
  }

  async function validateSyncAirdropPrereqs() {
    console.log("Wallet:", state.address);
    if (!state.address) {
      throw new Error("Connect your wallet first.");
    }

    if (!state.provider) {
      throw new Error("Connect your wallet first.");
    }

    const network = await state.provider.getNetwork();
    const chainId = Number(network.chainId);
    console.log("Network:", chainId);
    if (chainId !== 11155111) {
      throw new Error("Please switch to Sepolia network.");
    }

    console.log("Token address:", cfg.tokenAddress);
    if (!cfg.tokenAddress || cfg.tokenAddress.startsWith("0x0000")) {
      throw new Error("Token contract not found.");
    }

    const [tokenCode, rewardsCode] = await Promise.all([
      state.provider.getCode(cfg.tokenAddress),
      state.provider.getCode(cfg.rewardsAddress),
    ]);

    if (tokenCode === "0x") {
      throw new Error("Token contract not deployed.");
    }
    if (rewardsCode === "0x") {
      throw new Error("Token contract not found.");
    }
  }

  function setActionButtonState(button, isBusy, busyLabel, idleLabel) {
    if (!button) {
      return;
    }

    button.disabled = isBusy;
    button.textContent = isBusy ? busyLabel : idleLabel;
  }

  function updateExplorerLinks() {
    setExplorerHref(els.walletExplorer, state.address);
    setExplorerHref(els.tokenExplorer, cfg.tokenAddress);
    setExplorerHref(els.rewardsExplorer, cfg.rewardsAddress);
  }

  function resetWalletView() {
    state.provider = null;
    state.signer = null;
    state.address = cfg.defaultWalletAddress || "";

    if (els.balance) {
      els.balance.textContent = "0.0";
    }
    if (els.claimable) {
      els.claimable.textContent = "0.0";
    }

    updateWalletAddress(state.address);
    syncRecipientInput(state.address);
    updateExplorerLinks();
    setTxExplorer("");
    setBadgeState("idle");
  }

  async function refreshChainData() {
    if (!state.provider || !state.address) {
      return;
    }

    if (!cfg.tokenAddress || !cfg.rewardsAddress) {
      setStatus("Sepolia contracts not connected yet.", true);
      setHint("Add deployed EVFI token and rewards contract addresses to enable live wallet balance and claimable reward reads.");
      return;
    }

    const token = new ethers.Contract(cfg.tokenAddress, tokenAbi, state.provider);
    const rewards = new ethers.Contract(cfg.rewardsAddress, rewardsAbi, state.provider);

    try {
      const [balance, pending] = await Promise.all([
        token.balanceOf(state.address),
        rewards.pendingRewards(state.address),
      ]);

      if (els.balance) {
        els.balance.textContent = formatToken(balance);
      }
      if (els.claimable) {
        els.claimable.textContent = formatToken(pending);
      }

      setBadgeState("connected");
      setHint("Live Sepolia reads are active. Review EVFI balance, inspect contracts in the explorer, or claim pending rewards.");
      setStatus("Sepolia wallet connected.");
    } catch (error) {
      setStatus(error.shortMessage || error.message || "Failed to read onchain EVFI data.", true);
    }
  }

  async function connectWallet() {
    if (!window.ethereum) {
      setStatus("No injected wallet detected. Install MetaMask or another Sepolia-capable wallet.", true);
      showToast("No wallet detected in this browser.", "error");
      return;
    }

    try {
      setBadgeState("connecting");
      setHint("Approve the wallet connection request in MetaMask to continue.");

      state.provider = new ethers.BrowserProvider(window.ethereum);
      await state.provider.send("eth_requestAccounts", []);
      state.signer = await state.provider.getSigner();
      state.address = await state.signer.getAddress();
      updateWalletAddress(state.address);
      syncRecipientInput(state.address);

      try {
        await window.ethereum.request({
          method: "wallet_switchEthereumChain",
          params: [{ chainId: "0xaa36a7" }],
        });
      } catch (_) {
        // Keep going; the wallet may already be on Sepolia or reject switching.
      }

      updateExplorerLinks();
      setBadgeState("connected");
      showToast("Wallet connected successfully.", "success");
      await refreshChainData();
    } catch (error) {
      setBadgeState("error");
      setStatus(error?.shortMessage || error?.message || "Wallet connection failed.", true);
      showToast("Wallet connection failed.", "error");
    }
  }

  function disconnectWallet() {
    resetWalletView();
    setStatus("Wallet disconnected from this app session.", false);
    setHint("The manager wallet remains on the backend. Connect your user wallet again any time to read balances, claim rewards, or receive mileage-based EVFI.");
    showToast("Wallet disconnected.", "success");
  }

  async function claimRewards() {
    if (!state.signer || !cfg.rewardsAddress) {
      setStatus("Connect a Sepolia wallet first.", true);
      return;
    }

    const rewards = new ethers.Contract(cfg.rewardsAddress, rewardsAbi, state.signer);
    try {
      setStatus("Submitting claim transaction...");
      setHint("Confirm the claim transaction in your wallet.");
      const tx = await rewards.claim();
      await tx.wait();
      setStatus(`Claim confirmed: ${tx.hash}`);
      showToast("Claim confirmed on Sepolia.", "success");
      await refreshChainData();
    } catch (error) {
      setStatus(error.shortMessage || error.message || "Claim failed.", true);
      showToast("Claim transaction failed.", "error");
    }
  }

  async function assignRewards() {
    const vehicleId = els.assign?.dataset.vehicleId;
    const amount = els.assign?.dataset.defaultAmount;
    const adminKey = els.adminKey?.value?.trim();
    const recipientWallet = getRecipientWallet();

    if (!vehicleId) {
      setStatus("Vehicle context is missing for reward assignment.", true);
      return;
    }

    if (!adminKey) {
      setStatus("Enter the admin API key to assign test EVFI.", true);
      return;
    }

    try {
      setStatus("Assigning demo EVFI onchain...");
      setHint("Submitting a demo weekly reward assignment from the backend.");
      const response = await fetch(`/api/vehicle/${vehicleId}/assign-demo-reward`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-admin-key": adminKey,
        },
        body: JSON.stringify({
          wallet: recipientWallet,
          amountTokens: amount,
        }),
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Reward assignment failed");
      }

      setStatus(`Reward assignment confirmed: ${payload.batchId}`);
      if (payload.txHash) {
        setTxExplorer(payload.txHash);
        setHint(`Pending EVFI assigned to ${payload.wallet}. Track the assignment tx on Sepolia: ${payload.txHash}`);
      }
      showToast("Demo EVFI assigned.", "success");
      await refreshChainData();
    } catch (error) {
      setStatus(error.message || "Reward assignment failed.", true);
      showToast("Reward assignment failed.", "error");
    }
  }

  async function refreshAndDistribute() {
    const vehicleId = els.refreshAndDistribute?.dataset.vehicleId;
    const adminKey = els.adminKey?.value?.trim();
    const recipientWallet = getRecipientWallet();

    if (!vehicleId) {
      setStatus("Vehicle context is missing for sync distribution.", true);
      return;
    }

    if (!adminKey) {
      setStatus("Enter the admin API key to run sync + airdrop.", true);
      return;
    }

    try {
      await validateSyncAirdropPrereqs();
      console.log("Telemetry fetched");
      console.log("Mileage:", els.refreshAndDistribute?.dataset.defaultAmount || "pending recalculation");
      console.log("Reward calculated:", els.refreshAndDistribute?.dataset.defaultAmount || "server-calculated");
      setActionButtonState(els.refreshAndDistribute, true, "Processing...", "Sync + Airdrop");
      setStatus("Processing...", false);
      setHint("This flow refreshes telemetry, recalculates the mileage-based amount, and queues rewards for the recipient wallet.");
      const response = await fetch(`/api/vehicle/${vehicleId}/refresh-and-distribute`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-admin-key": adminKey,
        },
        body: JSON.stringify({
          wallet: recipientWallet,
        }),
      });

      const payload = await response.json();
      console.log("Sync + Airdrop response:", payload);
      if (!response.ok) {
        const details = payload?.error || {};
        const message = details.message || payload.error || "Sync distribution failed";
        const error = new Error(message);
        error.code = details.code;
        error.reason = details.reason;
        error.stack = details.stack || error.stack;
        throw error;
      }

      for (const step of payload.output?.logs || []) {
        console.log(step);
      }
      console.log("Transaction hash:", payload.txHash);
      setStatus(`Mileage sync and EVFI distribution confirmed: ${payload.batchId}`);
      setTxExplorer(payload.txHash || "");
      setHint(`Assigned ${formatNumber(payload.amountTokens)} EVFI to ${payload.wallet}. ${payload.txHash ? `Sepolia tx: ${payload.txHash}. ` : ""}Claim from that wallet to verify the end-to-end token flow.`);
      showToast("EVFI tokens successfully airdropped.", "success");
      console.log("Transaction confirmed");
      await refreshChainData();
    } catch (error) {
      console.error(error);
      const details = stringifyExtraError(error);
      setStatus(error.message || "Sync distribution failed.", true);
      if (details) {
        setHint(details);
      }
      showToast(error.message || "Sync + airdrop failed.", "error");
    } finally {
      setActionButtonState(els.refreshAndDistribute, false, "Processing...", "Sync + Airdrop");
    }
  }

  async function claimAirdrop() {
    const vehicleId = els.claimAirdrop?.dataset.vehicleId;
    const adminKey = els.adminKey?.value?.trim();
    const recipientWallet = getRecipientWallet();

    if (!vehicleId) {
      setStatus("Vehicle context is missing for airdrop claim.", true);
      return;
    }

    if (!adminKey) {
      setStatus("Enter the admin API key to claim the first-login mileage airdrop.", true);
      return;
    }

    try {
      await validateSyncAirdropPrereqs();
      setActionButtonState(els.claimAirdrop, true, "Claiming...", "Airdrop Claimed");
      setStatus("Minting first-login EVFI airdrop...");
      const response = await fetch(`/api/vehicle/${vehicleId}/claim-airdrop`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-admin-key": adminKey,
        },
        body: JSON.stringify({ wallet: recipientWallet }),
      });

      const payload = await response.json();
      if (!response.ok) {
        const details = payload?.error || {};
        throw new Error(details.message || payload.error || "Airdrop claim failed");
      }

      if (payload.txHash) {
        setTxExplorer(payload.txHash);
      }
      els.claimAirdrop.textContent = "Airdrop Claimed";
      setStatus(`Airdrop Claimed: ${formatNumber(payload.amountTokens)} EVFI`);
      setHint(payload.txHash ? `Airdrop mint confirmed on Sepolia: ${payload.txHash}` : "Airdrop already claimed.");
      showToast("Airdrop Claimed.", "success");
      await refreshChainData();
    } catch (error) {
      setStatus(error.message || "Airdrop claim failed.", true);
      showToast("Airdrop claim failed.", "error");
      setActionButtonState(els.claimAirdrop, false, "Claiming...", "Airdrop Available");
    }
  }

  function updateSportCountdown(endTime) {
    if (!els.sportMode || !els.sportModeStatus || !endTime) {
      return;
    }

    const tick = () => {
      const seconds = Math.max(0, Math.floor(endTime - Date.now() / 1000));
      if (seconds <= 0) {
        els.sportMode.classList.remove("sport-active");
        els.sportMode.dataset.active = "false";
        els.sportModeStatus.textContent = "Sport Mode available: 15 minutes, 1 use per day.";
        return;
      }
      const minutes = Math.floor(seconds / 60);
      const remainder = seconds % 60;
      els.sportModeStatus.textContent = `SPORT MODE ACTIVE - ${minutes}:${String(remainder).padStart(2, "0")} remaining`;
      window.setTimeout(tick, 1000);
    };
    tick();
  }

  function updateMockTokenMetrics() {
    const priceEl = document.getElementById("mockEvfiPrice");
    const capEl = document.getElementById("mockMarketCap");
    const supplyEl = document.getElementById("mockCirculatingSupply");
    const chartEl = document.getElementById("mockPriceChart");
    if (!priceEl || !capEl || !supplyEl) {
      return;
    }

    const supply = 100000000;
    const drift = Math.sin(Date.now() / 45000) * 0.004;
    const price = 0.04 + drift;
    priceEl.textContent = `$${formatNumber(price)}`;
    capEl.textContent = `$${formatNumber(price * supply)}`;
    supplyEl.textContent = formatNumber(supply);
    if (chartEl) {
      chartEl.style.filter = `hue-rotate(${Math.round(drift * 4000)}deg)`;
    }
  }

  async function activateSportMode() {
    const vehicleId = els.sportMode?.dataset.vehicleId;
    const recipientWallet = getRecipientWallet();
    if (!vehicleId) {
      setStatus("Vehicle context is missing for Sport Mode.", true);
      return;
    }

    try {
      const response = await fetch(`/api/vehicle/${vehicleId}/sport-mode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ wallet: recipientWallet }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Sport Mode failed.");
      }
      els.sportMode.classList.add("sport-active");
      els.sportMode.dataset.active = "true";
      els.sportMode.dataset.endTime = payload.endTime;
      updateSportCountdown(payload.endTime);
      setStatus("SPORT MODE ACTIVE");
      setHint("Negative scoring signals are ignored while Sport Mode is active. Positive rewards still count.");
      showToast("SPORT MODE ACTIVE.", "success");
    } catch (error) {
      setStatus(error.message || "Sport Mode failed.", true);
      showToast("Sport Mode unavailable.", "error");
    }
  }

  els.connect.addEventListener("click", connectWallet);
  if (els.disconnect) {
    els.disconnect.addEventListener("click", disconnectWallet);
  }
  if (els.claim) {
    els.claim.addEventListener("click", claimRewards);
  }
  if (els.assign) {
    els.assign.addEventListener("click", assignRewards);
  }
  if (els.refreshAndDistribute) {
    els.refreshAndDistribute.addEventListener("click", refreshAndDistribute);
  }
  if (els.claimAirdrop) {
    els.claimAirdrop.addEventListener("click", claimAirdrop);
  }
  if (els.sportMode) {
    els.sportMode.addEventListener("click", activateSportMode);
    if (els.sportMode.dataset.active === "true") {
      updateSportCountdown(Number(els.sportMode.dataset.endTime));
    }
  }

  resetWalletView();
  updateMockTokenMetrics();
  window.setInterval(updateMockTokenMetrics, 5000);

  if (!cfg.tokenAddress || !cfg.rewardsAddress) {
    setHint("Sepolia contracts not connected yet. Deploy EVFI contracts and add their addresses to the app config.");
  }
})();
