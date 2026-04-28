(function () {
  const cfg = window.EVFI_WEB3_CONFIG || {};
  const els = {
    syncMiles: document.getElementById("syncMilesButton"),
    refreshRewards: document.getElementById("refreshRewardsLink"),
    connect: document.getElementById("connectWalletButton"),
    connectLabel: document.getElementById("connectWalletButtonLabel"),
    addToken: document.getElementById("addTokenButton"),
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
    currentStreakValue: document.getElementById("currentStreakValue"),
    longestStreakValue: document.getElementById("longestStreakValue"),
    streakUpdatedAt: document.getElementById("streakUpdatedAt"),
    challengeCompletedCount: document.getElementById("challengeCompletedCount"),
    challengeTotalCount: document.getElementById("challengeTotalCount"),
    missionsUpdatedAt: document.getElementById("missionsUpdatedAt"),
    missionList: document.getElementById("missionList"),
    summaryOdometer: document.getElementById("vehicleSummaryOdometer"),
    detailsOdometer: document.getElementById("vehicleDetailsOdometer"),
    summaryLastSync: document.getElementById("vehicleSummaryLastSync"),
    chargeMeta: document.getElementById("vehicleChargeMeta"),
    telemetryScore: document.getElementById("telemetryScoreValue"),
    milesTracked: document.getElementById("milesTrackedValue"),
    airdropAmount: document.getElementById("airdropAmountValue"),
    historyBody: document.getElementById("rewardSyncHistoryBody"),
    weeklyScoreValue: document.getElementById("weeklyScoreValue"),
    weeklyScoreUpdatedAt: document.getElementById("weeklyScoreUpdatedAt"),
    scoreBreakdownVerifiedMiles: document.getElementById("scoreBreakdownVerifiedMiles"),
    scoreBreakdownActiveDays: document.getElementById("scoreBreakdownActiveDays"),
    scoreBreakdownParticipationBonus: document.getElementById("scoreBreakdownParticipationBonus"),
    scoreBreakdownEfficiencyScore: document.getElementById("scoreBreakdownEfficiencyScore"),
    scoreBreakdownChargeSessions: document.getElementById("scoreBreakdownChargeSessions"),
    scoreBreakdownChargingScore: document.getElementById("scoreBreakdownChargingScore"),
    scoreBreakdownMissionBonus: document.getElementById("scoreBreakdownMissionBonus"),
    scoreBreakdownPenaltyScore: document.getElementById("scoreBreakdownPenaltyScore"),
    scoreBreakdownStreakMultiplier: document.getElementById("scoreBreakdownStreakMultiplier"),
    scoreBreakdownStakingBoostPct: document.getElementById("scoreBreakdownStakingBoostPct"),
    scoreBreakdownStakingBonus: document.getElementById("scoreBreakdownStakingBonus"),
    scoreBreakdownAvgEfficiency: document.getElementById("scoreBreakdownAvgEfficiency"),
    scoreBreakdownBaselineEfficiency: document.getElementById("scoreBreakdownBaselineEfficiency"),
    scoreBreakdownHealthyCharges: document.getElementById("scoreBreakdownHealthyCharges"),
    scoreBreakdownHighSocCharges: document.getElementById("scoreBreakdownHighSocCharges"),
    scoreBreakdownPreBonus: document.getElementById("scoreBreakdownPreBonus"),
    scoreBreakdownEmissionFactor: document.getElementById("scoreBreakdownEmissionFactor"),
    scoreBreakdownWeeklyEvfi: document.getElementById("scoreBreakdownWeeklyEvfi"),
    scoreBreakdownTotalScore: document.getElementById("scoreBreakdownTotalScore"),
    scoreExplanationList: document.getElementById("scoreExplanationList"),
    utilityAvailableBalance: document.getElementById("utilityAvailableBalance"),
    utilityActiveStakeTier: document.getElementById("utilityActiveStakeTier"),
    utilityActiveStakeMeta: document.getElementById("utilityActiveStakeMeta"),
    unstakeUtilityButton: document.getElementById("unstakeUtilityButton"),
  };

  if (!els.connect) {
    return;
  }

  const state = {
    provider: null,
    signer: null,
    address: cfg.defaultWalletAddress || "",
    tokenDecimals: 18,
    toastTimer: null,
    connectState: "idle",
  };

  const CONNECTED_WALLET_STORAGE_KEY = "evfi_connected_wallet";
  const TOKEN_SUGGESTED_STORAGE_PREFIX = "evfi_token_suggested_";

  const tokenAbi = [
    "function balanceOf(address) view returns (uint256)",
    "function decimals() view returns (uint8)",
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

  function normalizeAddress(value) {
    if (!value) {
      return "";
    }
    try {
      return ethers.getAddress(String(value));
    } catch (_) {
      return String(value).toLowerCase();
    }
  }

  function connectedWalletStorageValue() {
    try {
      return window.localStorage.getItem(CONNECTED_WALLET_STORAGE_KEY) || "";
    } catch (_) {
      return "";
    }
  }

  function rememberConnectedWallet(address) {
    try {
      if (address) {
        window.localStorage.setItem(CONNECTED_WALLET_STORAGE_KEY, normalizeAddress(address));
      }
    } catch (_) {
      // Ignore storage errors in restricted browser contexts.
    }
  }

  function clearRememberedWallet() {
    try {
      window.localStorage.removeItem(CONNECTED_WALLET_STORAGE_KEY);
    } catch (_) {
      // Ignore storage errors in restricted browser contexts.
    }
  }

  function tokenSuggestedStorageKey(address) {
    return `${TOKEN_SUGGESTED_STORAGE_PREFIX}${normalizeAddress(address).toLowerCase()}`;
  }

  function wasTokenSuggested(address) {
    if (!address) {
      return false;
    }
    try {
      return window.localStorage.getItem(tokenSuggestedStorageKey(address)) === "true";
    } catch (_) {
      return false;
    }
  }

  function markTokenSuggested(address) {
    if (!address) {
      return;
    }
    try {
      window.localStorage.setItem(tokenSuggestedStorageKey(address), "true");
    } catch (_) {
      // Ignore storage errors in restricted browser contexts.
    }
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
    return Number(ethers.formatUnits(value, state.tokenDecimals)).toLocaleString(undefined, {
      maximumFractionDigits: 2,
    });
  }

  function formatNumber(value) {
    return Number(value || 0).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function formatInteger(value) {
    return Number(value || 0).toLocaleString(undefined, {
      maximumFractionDigits: 0,
    });
  }

  function formatTimestamp(value) {
    if (!value) {
      return "Never";
    }
    const date = new Date(Number(value) * 1000);
    if (Number.isNaN(date.getTime())) {
      return "Never";
    }
    return date.toLocaleString(undefined, {
      month: "short",
      day: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function missionLabelFor(challengeKey) {
    const labels = {
      drive_25_miles_weekly: "Drive 25 Miles This Week",
      sync_3_days_in_a_row: "Sync 3 Days In A Row",
      earn_250_evfi: "Earn 250 EVFi",
    };
    return labels[challengeKey] || String(challengeKey || "Mission");
  }

  function renderMissionRows(challenges) {
    if (!els.missionList || !Array.isArray(challenges)) {
      return;
    }

    const rows = challenges
      .slice()
      .sort((a, b) => String(a.challenge_key || "").localeCompare(String(b.challenge_key || "")))
      .map((challenge) => {
        const progress = Number(challenge.progress || 0);
        const target = Number(challenge.target || 0);
        const completionPct = target > 0 ? Math.min(100, (progress / target) * 100) : 0;
        const completed = Boolean(challenge.completed);
        return `
          <div class="mission-row">
            <div class="mission-copy">
              ${completed ? '<img class="mission-badge" src="/static/evfi-token-logo.png" alt="Completed mission badge">' : ""}
              <div>
                <strong>${missionLabelFor(challenge.challenge_key)}</strong>
                <div class="sub">Progress: <span class="value-tone-positive">${formatNumber(completionPct)}%</span></div>
              </div>
            </div>
            <span class="mission-pill" data-state="${completed ? "complete" : "active"}">${completed ? "Complete" : "Active"}</span>
          </div>
        `;
      })
      .join("");

    els.missionList.innerHTML = rows || "<div class='sub'>Sync the vehicle to start missions.</div>";
  }

  function applyGamificationState(gamification) {
    if (!gamification || !gamification.state) {
      return;
    }
    const stateData = gamification.state;
    const challenges = Array.isArray(gamification.challenges) ? gamification.challenges : [];
    const completedChallenges = challenges.filter((challenge) => Boolean(challenge.completed)).length;

    if (els.currentStreakValue) {
      els.currentStreakValue.textContent = formatInteger(stateData.current_streak || 0);
    }
    if (els.longestStreakValue) {
      els.longestStreakValue.textContent = formatInteger(stateData.longest_streak || 0);
    }
    if (els.streakUpdatedAt) {
      els.streakUpdatedAt.textContent = `Updated ${formatTimestamp(stateData.updated_at)}`;
    }
    if (els.challengeCompletedCount) {
      els.challengeCompletedCount.textContent = formatInteger(completedChallenges);
    }
    if (els.challengeTotalCount) {
      els.challengeTotalCount.textContent = formatInteger(challenges.length);
    }
    if (els.missionsUpdatedAt) {
      els.missionsUpdatedAt.textContent = `Updated ${formatTimestamp(stateData.updated_at)}`;
    }
    renderMissionRows(challenges);
  }

  function emitGamificationMessages(events) {
    if (!Array.isArray(events) || events.length === 0) {
      return;
    }
    const messages = events.filter(Boolean).map((item) => String(item).trim()).filter(Boolean);
    if (messages.length === 0) {
      return;
    }
    showToast(messages[0], "success");
    if (messages.length > 1) {
      setHint(messages.join(" "));
    }
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
    return normalizeAddress(els.distributionRecipient?.value?.trim() || state.address || cfg.defaultWalletAddress);
  }

  async function getWalletActionHeaders(action, vehicleId, wallet) {
    if (!window.ethereum || !window.ethers) {
      throw new Error("Connect a Sepolia wallet first.");
    }
    state.provider = state.provider || new ethers.BrowserProvider(window.ethereum);
    if (!state.signer) {
      await state.provider.send("eth_requestAccounts", []);
      state.signer = await state.provider.getSigner();
      state.address = await state.signer.getAddress();
      rememberConnectedWallet(state.address);
      updateWalletAddress(state.address);
      syncRecipientInput(state.address);
    }
    const signerAddress = normalizeAddress(await state.signer.getAddress());
    const recipientWallet = normalizeAddress(wallet);
    if (recipientWallet && signerAddress !== recipientWallet) {
      throw new Error("The connected wallet must match the recipient wallet.");
    }
    const message = [
      "EVFi wallet action",
      `Action: ${action}`,
      `Vehicle: ${vehicleId}`,
      `Wallet: ${signerAddress}`,
      `Timestamp: ${Date.now()}`,
    ].join(" | ");
    const signature = await state.signer.signMessage(message);
    return {
      "x-wallet-address": signerAddress,
      "x-wallet-message": message,
      "x-wallet-signature": signature,
    };
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

  function updateAddTokenButton() {
    if (!els.addToken) {
      return;
    }
    const connected = Boolean(state.provider && state.address);
    const suggested = connected && wasTokenSuggested(state.address);
    els.addToken.disabled = !connected || !cfg.tokenAddress;
    els.addToken.textContent = suggested ? "EVFi Added" : "Add EVFi to MetaMask";
  }

  function updateExplorerLinks() {
    setExplorerHref(els.walletExplorer, state.address);
    setExplorerHref(els.tokenExplorer, cfg.tokenAddress);
    setExplorerHref(els.rewardsExplorer, cfg.rewardsAddress);
  }

  async function addTokenToWallet(reason) {
    const why = reason || "manual";
    console.log("[evfi] wallet_watchAsset check", {
      reason: why,
      walletAddress: state.address || null,
      alreadySuggested: wasTokenSuggested(state.address),
    });

    if (!state.provider || !state.address) {
      setStatus("Connect a Sepolia wallet before adding EVFi.", true);
      return;
    }
    if (!window.ethereum || !cfg.tokenAddress) {
      setStatus("EVFi token metadata is not available.", true);
      return;
    }
    if (wasTokenSuggested(state.address)) {
      console.log("[evfi] wallet_watchAsset skipped", {
        reason: "already_suggested_for_wallet",
        walletAddress: state.address,
      });
      setStatus("EVFi was already suggested for this wallet.", false);
      setHint("MetaMask token import is no longer triggered automatically. Use this button only when you want to re-add the token manually.");
      updateAddTokenButton();
      return;
    }

    try {
      console.log("[evfi] wallet_watchAsset called", { reason: why, walletAddress: state.address });
      const added = await window.ethereum.request({
        method: "wallet_watchAsset",
        params: {
          type: "ERC20",
          options: {
            address: cfg.tokenAddress,
            symbol: "EVFI",
            decimals: state.tokenDecimals,
            image: `${window.location.origin}/static/evfi-token-logo.png`,
          },
        },
      });
      if (added) {
        markTokenSuggested(state.address);
      }
      console.log("[evfi] wallet_watchAsset result", { reason: why, walletAddress: state.address, added: Boolean(added) });
      updateAddTokenButton();
      setStatus(added ? "EVFi token added in MetaMask." : "EVFi token suggestion dismissed.", !added);
    } catch (error) {
      console.log("[evfi] wallet_watchAsset failed", {
        reason: why,
        walletAddress: state.address,
        message: error?.message || "Unknown MetaMask error",
      });
      setStatus(error?.message || "Failed to suggest EVFi in MetaMask.", true);
    }
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
    updateAddTokenButton();
  }

  async function refreshChainData() {
    if (!state.provider || !state.address) {
      return;
    }

    if (!cfg.tokenAddress || !cfg.rewardsAddress) {
      setStatus("Sepolia contracts not connected yet.", true);
      setHint("Add deployed EVFi token and rewards contract addresses to enable live wallet balance and claimable reward reads.");
      return;
    }

    const token = new ethers.Contract(cfg.tokenAddress, tokenAbi, state.provider);
    const rewards = new ethers.Contract(cfg.rewardsAddress, rewardsAbi, state.provider);

    try {
      const [balance, pending, decimals] = await Promise.all([
        token.balanceOf(state.address),
        rewards.pendingRewards(state.address),
        token.decimals(),
      ]);
      state.tokenDecimals = Number(decimals);

      if (els.balance) {
        els.balance.textContent = formatToken(balance);
      }
      if (els.claimable) {
        els.claimable.textContent = formatToken(pending);
      }

      setBadgeState("connected");
      setHint("Live Sepolia reads are active. Review EVFi balance, inspect contracts in the explorer, claim pending rewards, or add EVFi to MetaMask when you choose.");
      setStatus("Sepolia wallet connected.");
      updateAddTokenButton();
    } catch (error) {
      setStatus(error.shortMessage || error.message || "Failed to read onchain EVFi data.", true);
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
      rememberConnectedWallet(state.address);
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
      updateAddTokenButton();
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
    clearRememberedWallet();
    resetWalletView();
    setStatus("Wallet disconnected from this app session.", false);
    setHint("The manager wallet remains on the backend. Connect your user wallet again any time to read balances, claim rewards, or receive mileage-based EVFi.");
    showToast("Wallet disconnected.", "success");
  }

  async function reconcileConnectedWallet(accounts, reason) {
    const normalizedAccounts = Array.isArray(accounts) ? accounts.map((item) => normalizeAddress(item)).filter(Boolean) : [];
    if (normalizedAccounts.length === 0) {
      console.log("[evfi] wallet session cleared", { reason });
      clearRememberedWallet();
      resetWalletView();
      setStatus("Wallet not connected yet.", false);
      return;
    }

    state.provider = state.provider || new ethers.BrowserProvider(window.ethereum);
    const preferred = normalizeAddress(connectedWalletStorageValue());
    const nextAddress = normalizedAccounts.includes(preferred) ? preferred : normalizedAccounts[0];
    state.signer = await state.provider.getSigner(nextAddress);
    state.address = nextAddress;
    rememberConnectedWallet(nextAddress);
    updateWalletAddress(nextAddress);
    syncRecipientInput(nextAddress);
    updateExplorerLinks();
    updateAddTokenButton();
    console.log("[evfi] wallet session active", { reason, walletAddress: nextAddress });
    await refreshChainData();
  }

  async function restoreWalletSession() {
    if (!window.ethereum) {
      return;
    }

    const rememberedWallet = connectedWalletStorageValue();
    if (!rememberedWallet) {
      updateAddTokenButton();
      return;
    }

    try {
      state.provider = new ethers.BrowserProvider(window.ethereum);
      const accounts = await state.provider.send("eth_accounts", []);
      await reconcileConnectedWallet(accounts, "restore_session");
    } catch (error) {
      console.log("[evfi] wallet session restore failed", { message: error?.message || "Unknown restore error" });
      clearRememberedWallet();
      resetWalletView();
    }
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
      setStatus("Enter the admin API key to assign test EVFi.", true);
      return;
    }

    try {
      setStatus("Assigning demo EVFi onchain...");
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
        setHint(`Pending EVFi assigned to ${payload.wallet}. Track the assignment tx on Sepolia: ${payload.txHash}`);
      }
      showToast("Demo EVFi assigned.", "success");
      applyGamificationState(payload.gamification);
      emitGamificationMessages(payload.gamificationEvents);
      await refreshChainData();
    } catch (error) {
      setStatus(error.message || "Reward assignment failed.", true);
      showToast("Reward assignment failed.", "error");
    }
  }

  async function refreshAndDistribute() {
    const vehicleId = els.refreshAndDistribute?.dataset.vehicleId;
    const recipientWallet = getRecipientWallet();

    if (!vehicleId) {
      setStatus("Vehicle context is missing for sync distribution.", true);
      return;
    }

    try {
      await validateSyncAirdropPrereqs();
      const walletHeaders = await getWalletActionHeaders("refresh-and-distribute", vehicleId, recipientWallet);
      console.log("Telemetry fetched");
      console.log("Mileage:", els.refreshAndDistribute?.dataset.defaultAmount || "pending recalculation");
      console.log("Reward calculated:", els.refreshAndDistribute?.dataset.defaultAmount || "server-calculated");
      setActionButtonState(els.refreshAndDistribute, true, "Processing...", "Sync + Weekly EVFi");
      setStatus("Processing...", false);
      setHint("This flow refreshes telemetry, recalculates the canonical weekly score, and assigns the current weekly EVFi amount for the recipient wallet.");
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
      console.log("Sync + Weekly EVFi response:", payload);
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
      setStatus(`Mileage sync and weekly EVFi assignment confirmed: ${payload.batchId}`);
      setTxExplorer(payload.txHash || "");
      setHint(`Assigned ${formatNumber(payload.amountTokens)} EVFi to ${payload.wallet}. ${payload.txHash ? `Sepolia tx: ${payload.txHash}. ` : ""}This amount comes from the weekly score and emission factor, not a one-time airdrop.`);
      showToast("Weekly EVFi assigned.", "success");
      console.log("Transaction confirmed");
      applyGamificationState(payload.gamification);
      emitGamificationMessages(payload.gamificationEvents);
      await refreshChainData();
      updateMockTokenMetrics();
    } catch (error) {
      console.error(error);
      const details = stringifyExtraError(error);
      setStatus(error.message || "Sync distribution failed.", true);
      if (details) {
        setHint(details);
      }
      showToast(error.message || "Weekly EVFi assignment failed.", "error");
    } finally {
      setActionButtonState(els.refreshAndDistribute, false, "Processing...", "Sync + Weekly EVFi");
    }
  }

  async function claimAirdrop() {
    const vehicleId = els.claimAirdrop?.dataset.vehicleId;
    const recipientWallet = getRecipientWallet();

    if (!vehicleId) {
      setStatus("Vehicle context is missing for airdrop claim.", true);
      return;
    }

    try {
      await validateSyncAirdropPrereqs();
      const walletHeaders = await getWalletActionHeaders("claim-airdrop", vehicleId, recipientWallet);
      setActionButtonState(els.claimAirdrop, true, "Claiming...", "Airdrop Claimed");
      setStatus("Minting onboarding EVFi airdrop...");
      const response = await fetch(`/api/vehicle/${vehicleId}/claim-airdrop`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...walletHeaders,
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
      setStatus(`Airdrop Claimed: ${formatNumber(payload.amountTokens)} EVFi`);
      setHint(payload.txHash ? `Onboarding airdrop mint confirmed on Sepolia: ${payload.txHash}` : "Onboarding airdrop already claimed.");
      showToast("Airdrop Claimed.", "success");
      applyGamificationState(payload.gamification);
      emitGamificationMessages(payload.gamificationEvents);
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
      const labels = ["Apr 10", "Apr 11", "Apr 12", "Apr 13", "Apr 14", "Apr 15", "Apr 16"];
      const data = [0.052, 0.082, 0.047, 0.118, 0.074, 0.151, 0.097].map((value, index) => {
        const noise = Math.sin(Date.now() / 52000 + index * 1.9) * 0.006;
        return Number((value + noise).toFixed(3));
      });
      const minY = 0.03;
      const maxY = 0.18;
      const points = data.map((value, index) => {
        const x = 58 + index * 54;
        const y = 142 - ((value - minY) / (maxY - minY)) * 104;
        return [x, y];
      });
      const pointString = points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
      const yLabels = [0.04, 0.08, 0.12, 0.16];
      chartEl.innerHTML = `
        <svg viewBox="0 0 430 188" class="line-chart" role="img" aria-label="EVFi price over time">
          <defs>
            <linearGradient id="evfiLineFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stop-color="rgba(32,227,124,.22)" />
              <stop offset="100%" stop-color="rgba(32,227,124,0)" />
            </linearGradient>
          </defs>
          <rect x="0" y="0" width="430" height="188" rx="18" fill="transparent"></rect>
          ${yLabels.map((label) => {
            const y = 142 - ((label - minY) / (maxY - minY)) * 104;
            return `<line x1="48" x2="398" y1="${y}" y2="${y}" stroke="rgba(210,216,228,.16)" stroke-width="1"/><text x="10" y="${y + 4}" fill="rgba(210,216,228,.62)" font-size="11">${label.toFixed(2)}</text>`;
          }).join("")}
          ${labels.map((label, index) => {
            const x = 58 + index * 54;
            return `<line x1="${x}" x2="${x}" y1="34" y2="146" stroke="rgba(210,216,228,.08)" stroke-width="1"/><text x="${x - 18}" y="170" fill="rgba(210,216,228,.62)" font-size="10">${label}</text>`;
          }).join("")}
          <text x="8" y="24" fill="rgba(210,216,228,.7)" font-size="11">Price</text>
          <text x="368" y="184" fill="rgba(210,216,228,.7)" font-size="11">Date</text>
          <polygon points="${points[0][0]},142 ${pointString} ${points[points.length - 1][0]},142" fill="url(#evfiLineFill)"></polygon>
          <polyline points="${pointString}" fill="none" stroke="#20e37c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></polyline>
          ${points.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="3" fill="#20e37c" stroke="#071018" stroke-width="2"></circle>`).join("")}
        </svg>`;
      fetch("/api/log-ui-event", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event: "chart_data_updated", points: data.length }),
      }).catch(() => {});
    }
  }

  async function runUtilityAction(actionType, actionKey) {
    const vehicleId = els.syncMiles?.dataset.vehicleId || els.refreshRewards?.dataset.vehicleId;
    const adminKey = els.adminKey?.value?.trim();
    const wallet = getRecipientWallet();
    if (!vehicleId) {
      setStatus("Vehicle context is missing for EVFi utility actions.", true);
      return;
    }
    if (actionType === "onchain_stake_hint") {
      const selector = `.utility-action-button[data-action-type="onchain_stake_hint"][data-action-key="${actionKey}"]`;
      const button = document.querySelector(selector);
      const amount = button?.dataset.stakeEvfi || "";
      window.dispatchEvent(new CustomEvent("evfi:prefillStake", { detail: { amount, tier: actionKey } }));
      setStatus(amount ? `Ready to stake ${amount} EVFi onchain.` : "Use the onchain staking panel to stake EVFi.");
      setHint("Choose the lock period, then approve and stake in MetaMask. The dashboard reads the staking contract directly.");
      return;
    }
    if (!adminKey) {
      setStatus("Enter the admin API key to use EVFi utility actions in this demo.", true);
      return;
    }

    let endpoint = "";
    let body = { wallet };
    if (actionType === "stake") {
      endpoint = `/api/vehicle/${vehicleId}/utility/stake`;
      body.tierKey = actionKey;
    } else if (actionType === "unstake") {
      endpoint = `/api/vehicle/${vehicleId}/utility/unstake`;
    } else {
      endpoint = `/api/vehicle/${vehicleId}/utility/redeem`;
      body.actionKey = actionKey;
    }

    try {
      setStatus("Processing EVFi utility action...", false);
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...walletHeaders,
        },
        body: JSON.stringify(body),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Utility action failed.");
      }
      applyUtilityRewardUpdate(payload);
      setStatus("EVFi utility action completed.");
      if (actionType === "stake") {
        showToast("Stake activated.", "success");
      } else if (actionType === "unstake") {
        showToast("Stake released.", "success");
      } else {
        showToast("EVFi utility redeemed.", "success");
      }
    } catch (error) {
      setStatus(error.message || "Utility action failed.", true);
      showToast(error.message || "Utility action failed.", "error");
    }
  }

  function setValueToneClass(el, value) {
    if (!el) {
      return;
    }
    el.classList.remove("value-tone-positive", "value-tone-negative");
    el.classList.add(Number(value || 0) > 0 ? "value-tone-positive" : "value-tone-negative");
  }

  function applyWeeklyScoreBreakdown(breakdown, emissionFactor, weeklyEvfi) {
    const data = breakdown || {};
    const setText = (el, value) => {
      if (el) {
        el.textContent = value;
      }
    };

    setText(els.scoreBreakdownVerifiedMiles, formatNumber(data.verifiedMiles || 0));
    setText(els.scoreBreakdownActiveDays, formatInteger(data.activeDays || 0));
    setText(els.scoreBreakdownParticipationBonus, formatNumber(data.participationBonus || 0));
    setText(els.scoreBreakdownEfficiencyScore, formatNumber(data.efficiencyScore || 0));
    setText(els.scoreBreakdownChargeSessions, formatInteger(data.chargeSessions || 0));
    setText(els.scoreBreakdownChargingScore, formatNumber(data.chargingScore || 0));
    setText(els.scoreBreakdownMissionBonus, formatNumber(data.missionBonus || 0));
    setText(els.scoreBreakdownPenaltyScore, formatNumber(data.penaltyScore || 0));
    setText(els.scoreBreakdownStreakMultiplier, `${Number(data.streakMultiplier || 1).toFixed(2)}x`);
    setText(els.scoreBreakdownStakingBoostPct, `${Number(data.stakingBoostPct || 0).toFixed(2)}%`);
    setText(els.scoreBreakdownStakingBonus, formatNumber(data.stakingBonus || 0));
    setText(els.scoreBreakdownAvgEfficiency, formatNumber(data.avgEfficiencyWhmi || 0));
    setText(els.scoreBreakdownBaselineEfficiency, formatNumber(data.baselineEfficiencyWhmi || 0));
    setText(els.scoreBreakdownHealthyCharges, formatInteger(data.healthyChargeSessions || 0));
    setText(els.scoreBreakdownHighSocCharges, formatInteger(data.highSocChargeSessions || 0));
    setText(els.scoreBreakdownPreBonus, formatNumber(data.preBonusScore || 0));
    setText(els.scoreBreakdownEmissionFactor, Number(emissionFactor || 0).toFixed(6));
    setText(els.scoreBreakdownWeeklyEvfi, formatNumber(weeklyEvfi || 0));
    setText(els.scoreBreakdownTotalScore, formatNumber(data.totalScore || 0));
  }

  function applyScoreExplanations(explanations) {
    if (!els.scoreExplanationList) {
      return;
    }
    const rows = Array.isArray(explanations) && explanations.length > 0
      ? explanations.map((item) => `<li class="score-explanation-item">${String(item)}</li>`).join("")
      : "<li class='score-explanation-item'>Sync the vehicle to generate this week's reward explanations.</li>";
    els.scoreExplanationList.innerHTML = rows;
  }

  function applyUtilityState(utilityState) {
    if (!utilityState) {
      return;
    }
    if (els.utilityAvailableBalance) {
      els.utilityAvailableBalance.textContent = formatNumber(utilityState.balance?.available || 0);
    }
    if (els.utilityActiveStakeTier) {
      els.utilityActiveStakeTier.textContent = utilityState.activeStake?.tierKey
        ? String(utilityState.activeStake.tierKey).replace(/^\w/, (char) => char.toUpperCase())
        : "None";
    }
    if (els.utilityActiveStakeMeta) {
      els.utilityActiveStakeMeta.textContent = utilityState.activeStake
        ? `${formatNumber(utilityState.activeStake.stakeEvfi || 0)} EVFi staked • +${formatNumber(utilityState.activeStake.rewardBoostPct || 0)}% boost`
        : "No active staking tier yet.";
    }
    if (els.unstakeUtilityButton) {
      els.unstakeUtilityButton.disabled = !utilityState.activeStake;
    }
  }

  function applyUtilityRewardUpdate(payload) {
    if (!payload) {
      return;
    }
    applyUtilityState(payload.utilityState);
    if (els.weeklyScoreValue) {
      const totalScore = Number(payload.weeklyScore?.totalScore || 0);
      els.weeklyScoreValue.textContent = `${formatNumber(totalScore)} pts`;
      setValueToneClass(els.weeklyScoreValue, totalScore);
    }
    applyWeeklyScoreBreakdown(
      payload.weeklyScore?.breakdown || {},
      payload.rewardPreview?.emissionFactor || 0,
      payload.rewardPreview?.estimatedEvfi || 0,
    );
    applyScoreExplanations(payload.weeklyScore?.explanations || []);
    if (els.telemetryScore) {
      els.telemetryScore.textContent = formatNumber(payload.weeklyScore?.totalScore || 0);
      setValueToneClass(els.telemetryScore, payload.weeklyScore?.totalScore || 0);
    }
    if (els.airdropAmount) {
      els.airdropAmount.textContent = formatNumber(payload.rewardPreview?.estimatedEvfi || 0);
      setValueToneClass(els.airdropAmount, payload.rewardPreview?.estimatedEvfi || 0);
    }
  }

  function renderRewardHistoryRows(events) {
    if (!els.historyBody) {
      return;
    }
    if (!Array.isArray(events) || events.length === 0) {
      els.historyBody.innerHTML = `
        <tr>
          <td colspan="4" class="muted">No sync history yet. Click Sync Miles.</td>
        </tr>
      `;
      return;
    }

    els.historyBody.innerHTML = events
      .map((event) => `
        <tr>
          <td>${event.syncedAtLabel || "Never"}</td>
          <td>${formatNumber(event.odometer)}</td>
          <td>${formatNumber(event.milesAdded)}</td>
          <td class="gain ${Number(event.scoreAdded || 0) > 0 ? "value-tone-positive" : "value-tone-negative"}">+${formatNumber(event.scoreAdded)}</td>
        </tr>
      `)
      .join("");
  }

  function applySyncResponse(payload) {
    if (!payload) {
      return;
    }

    const odometerValue = Number(payload.odometer || 0).toFixed(1);
    if (els.summaryOdometer) {
      els.summaryOdometer.textContent = odometerValue;
    }
    if (els.detailsOdometer) {
      els.detailsOdometer.textContent = odometerValue;
    }
    if (els.summaryLastSync) {
      els.summaryLastSync.textContent = payload.summary?.lastSyncedLabel || "Never";
    }
    if (els.telemetryScore) {
      els.telemetryScore.textContent = formatNumber(payload.summary?.telemetryScore || 0);
      setValueToneClass(els.telemetryScore, payload.summary?.telemetryScore || 0);
    }
    if (els.milesTracked) {
      els.milesTracked.textContent = formatNumber(payload.summary?.totalMiles || 0);
      setValueToneClass(els.milesTracked, payload.summary?.totalMiles || 0);
    }
    if (els.airdropAmount) {
      els.airdropAmount.textContent = formatNumber(payload.summary?.recommendedAssignment || 0);
      setValueToneClass(els.airdropAmount, payload.summary?.recommendedAssignment || 0);
    }
    if (els.weeklyScoreValue) {
      const totalScore = Number(payload.weeklyScore?.totalScore || 0);
      els.weeklyScoreValue.textContent = `${formatNumber(totalScore)} pts`;
      els.weeklyScoreValue.dataset.countUp = totalScore.toFixed(2);
      setValueToneClass(els.weeklyScoreValue, totalScore);
    }
    if (els.weeklyScoreUpdatedAt) {
      els.weeklyScoreUpdatedAt.textContent = `Updated ${payload.weeklyScore?.updatedAtLabel || "Never"}`;
    }
    applyWeeklyScoreBreakdown(
      payload.weeklyScore?.breakdown || {},
      payload.summary?.emissionFactor || 0,
      payload.summary?.recommendedAssignment || 0,
    );
    applyScoreExplanations(payload.weeklyScore?.explanations || []);
    applyUtilityState(payload.tokenUtility);
    if (els.chargeMeta) {
      const existingMeta = els.chargeMeta.textContent || "";
      const refreshedMeta = existingMeta.replace(/Last sync .*$/, `Last sync ${payload.summary?.lastSyncedLabel || "Never"}`);
      els.chargeMeta.textContent = refreshedMeta;
    }

    renderRewardHistoryRows(payload.events || []);
    applyGamificationState(payload.gamification);
    animateCountUp();
  }

  async function syncMiles() {
    const vehicleId = els.syncMiles?.dataset.vehicleId || els.refreshRewards?.dataset.vehicleId;
    const walletBeforeSync = state.address || connectedWalletStorageValue() || cfg.defaultWalletAddress || "";

    if (!vehicleId) {
      setStatus("Vehicle context is missing for mileage sync.", true);
      return;
    }

    try {
      console.log("[evfi] sync wallet before", { walletAddress: walletBeforeSync || null });
      setActionButtonState(els.syncMiles, true, "Syncing...", "Sync Miles");
      setStatus("Syncing Tesla telemetry...", false);
      setHint("Fetching the latest odometer, calculating mileage delta, and updating the dashboard without reloading the page.");

      const response = await fetch(`/api/vehicle/${vehicleId}/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          wallet: state.address || connectedWalletStorageValue() || cfg.defaultWalletAddress || "",
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Mileage sync failed.");
      }

      console.log("[evfi] sync reward delta", {
        previousOdometer: payload.events?.[1]?.odometer ?? null,
        currentOdometer: payload.odometer,
        milesAdded: payload.events?.[0]?.milesAdded ?? 0,
        scoreAdded: payload.events?.[0]?.scoreAdded ?? 0,
      });
      applySyncResponse(payload);
      console.log("[evfi] sync wallet after", { walletAddress: state.address || null });
      setStatus("Mileage sync complete.");
      setHint(`Latest sync recorded ${formatNumber(payload.events?.[0]?.milesAdded || 0)} miles and ${formatNumber(payload.events?.[0]?.scoreAdded || 0)} score.`);
      showToast("Mileage synced.", "success");
      await refreshChainData();
    } catch (error) {
      console.error(error);
      setStatus(error.message || "Mileage sync failed.", true);
      showToast("Mileage sync failed.", "error");
    } finally {
      setActionButtonState(els.syncMiles, false, "Syncing...", "Sync Miles");
    }
  }

  function animateCountUp() {
    document.querySelectorAll("[data-count-up]").forEach((el) => {
      const target = Number(el.dataset.countUp || 0);
      const suffix = el.textContent.replace(/[0-9.,-]/g, "").trim();
      const start = performance.now();
      const duration = 300;
      const step = (now) => {
        const progress = Math.min(1, (now - start) / duration);
        const value = target * progress;
        el.textContent = `${formatNumber(value)}${suffix ? ` ${suffix}` : ""}`;
        if (progress < 1) {
          requestAnimationFrame(step);
        }
      };
      requestAnimationFrame(step);
    });
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

  if (els.syncMiles) {
    els.syncMiles.addEventListener("click", syncMiles);
  }
  if (els.refreshRewards) {
    els.refreshRewards.addEventListener("click", (event) => {
      event.preventDefault();
      syncMiles();
    });
  }
  els.connect.addEventListener("click", connectWallet);
  if (els.addToken) {
    els.addToken.addEventListener("click", () => addTokenToWallet("manual_button"));
  }
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
  document.querySelectorAll(".utility-action-button[data-action-type]").forEach((button) => {
    button.addEventListener("click", () => {
      runUtilityAction(button.dataset.actionType || "", button.dataset.actionKey || "");
    });
  });
  if (els.unstakeUtilityButton) {
    els.unstakeUtilityButton.addEventListener("click", () => runUtilityAction("unstake", ""));
  }
  if (els.sportMode) {
    els.sportMode.addEventListener("click", activateSportMode);
    if (els.sportMode.dataset.active === "true") {
      updateSportCountdown(Number(els.sportMode.dataset.endTime));
    }
  }

  resetWalletView();
  updateMockTokenMetrics();
  animateCountUp();
  window.setInterval(updateMockTokenMetrics, 5000);
  restoreWalletSession();

  if (window.ethereum?.on) {
    window.ethereum.on("accountsChanged", (accounts) => {
      reconcileConnectedWallet(accounts, "accounts_changed").catch((error) => {
        console.error(error);
        disconnectWallet();
      });
    });
    window.ethereum.on("chainChanged", () => {
      restoreWalletSession().catch((error) => {
        console.error(error);
      });
    });
  }

  if (!cfg.tokenAddress || !cfg.rewardsAddress) {
    setHint("Sepolia contracts not connected yet. Deploy EVFi contracts and add their addresses to the app config.");
  }
})();
