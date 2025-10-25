// This script runs in the page context and can intercept WebSockets PASSIVELY
(function() {
  'use strict';
  
  console.log('%c🚀 Stake Crash Monitor - Starting...', 'color: #00ff00; font-size: 16px; font-weight: bold;');
  
  // Store original WebSocket
  const OriginalWebSocket = window.WebSocket;
  console.log('✔️ Original WebSocket saved:', OriginalWebSocket);
  
  // Array to store websocket connections
  const websocketConnections = [];
  let currentWebSocketIndex = 0;
  
  // Current multiplier data
  let currentMultiplier = null;
  let lastMultiplier = null;
  let gameStatus = null;
  let lastGameId = null;
  
  // Game tracking for logging
  let currentGameData = {
    eventId: null,
    startTime: null,
    endTime: null,
    crashMultiplier: null,
    totalCashedIn: 0,
    totalCashedOut: 0,
    hash: null
  };
  
  // Historical games storage
  let allGames = [];
  let historicalGamesGenerated = false;
  
  // File handles for persistent logging (CSV only)
  let csvFileHandle = null;
  let trimCsvFileHandle = null;
  let useTrimFiles = false;
  let mergeInProgress = false;
  let queuedGames = [];
  
  const SEED = '0000000000000000001b34dc6a1e86083f95500b096231436e9b25cbdd0075c4';
  const DROPBOX_CSV_URL = 'https://www.dropbox.com/scl/fi/ra42jqv8n2y4mhp97fypw/crash_trim.csv?rlkey=m95oy0qh49j1545km552wh9wv&st=6ml4zi2w&dl=1';
  
  // BTC price cache
  let btcPriceCache = {
    price: null,
    timestamp: 0,
    cacheDuration: 60000
  };
  
  let nextGameNumber = 1;
  
  // BTC Price API Integration
  async function getBTCPrice() {
    const now = Date.now();
    
    if (btcPriceCache.price && (now - btcPriceCache.timestamp) < btcPriceCache.cacheDuration) {
      return btcPriceCache.price;
    }
    
    try {
      const response = await fetch('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd');
      const data = await response.json();
      
      if (data && data.bitcoin && data.bitcoin.usd) {
        btcPriceCache.price = data.bitcoin.usd;
        btcPriceCache.timestamp = now;
        console.log(`💰 BTC Price fetched: $${btcPriceCache.price}`);
        return btcPriceCache.price;
      }
    } catch (e) {
      console.error('❌ Failed to fetch BTC price:', e);
    }
    
    return btcPriceCache.price;
  }
  
  async function convertToBTC(amount, currency, btcPrice) {
    if (!amount || !currency || !btcPrice) return null;
    
    if (currency.toUpperCase() === 'BTC') {
      return amount;
    }
    
    return amount / btcPrice;
  }
  
  // Hash and Multiplier Calculation
  async function sha256(message) {
    const msgBuffer = new TextEncoder().encode(message);
    const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  }
  
  async function hmacSHA256(key, message) {
    const encoder = new TextEncoder();
    const keyData = encoder.encode(key);
    const messageData = encoder.encode(message);
    
    const cryptoKey = await crypto.subtle.importKey(
      'raw',
      keyData,
      { name: 'HMAC', hash: 'SHA-256' },
      false,
      ['sign']
    );
    
    const signature = await crypto.subtle.sign('HMAC', cryptoKey, messageData);
    const hashArray = Array.from(new Uint8Array(signature));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  }
  
  async function calculateMultiplier(gameHash) {
    const hmacResult = await hmacSHA256(gameHash, SEED);
    const first8Chars = hmacResult.substring(0, 8);
    const decimalValue = parseInt(first8Chars, 16);
    const rawMultiplier = (Math.pow(2, 32) / (decimalValue + 1)) * 0.99;
    const multiplierValue = Math.max(1, rawMultiplier);
    const finalMultiplier = Math.floor(multiplierValue * 100) / 100;
    return finalMultiplier;
  }
  
  async function generatePreviousHash(currentHash) {
    return await sha256(currentHash);
  }
  
  // Download CSV from Dropbox via extension background
  async function downloadDropboxCSV() {
    updateHashGenStatus('Downloading pre-generated history...', '#ffaa00');
    
    try {
      // Send message to content script to download via extension
      return new Promise((resolve, reject) => {
        window.postMessage({ 
          type: 'DOWNLOAD_DROPBOX_CSV',
          url: DROPBOX_CSV_URL 
        }, '*');
        
        // Listen for response
        const listener = (event) => {
          if (event.source !== window) return;
          
          if (event.data.type === 'DROPBOX_CSV_DOWNLOADED') {
            window.removeEventListener('message', listener);
            if (event.data.success) {
              console.log('✔️ Downloaded CSV from Dropbox');
              resolve(event.data.csvText);
            } else {
              reject(new Error(event.data.error || 'Download failed'));
            }
          }
        };
        
        window.addEventListener('message', listener);
        
        // Timeout after 30 seconds
        setTimeout(() => {
          window.removeEventListener('message', listener);
          reject(new Error('Download timeout'));
        }, 30000);
      });
    } catch (e) {
      console.error('❌ Failed to download Dropbox CSV:', e);
      throw e;
    }
  }
  
  // Parse CSV and get last game number
  function parseCSVAndGetLastGame(csvText) {
    const lines = csvText.split('\n').filter(line => line.trim());
    
    // Skip header
    const dataLines = lines.slice(1);
    
    if (dataLines.length === 0) {
      return { lastGameNumber: 0, games: [] };
    }
    
    // Parse all games
    const games = dataLines.map(line => {
      const parts = line.split(',');
      return {
        gameNumber: parseInt(parts[0]),
        duration: parts[1] ? parseFloat(parts[1]) : null,
        crashMultiplier: parseFloat(parts[2]),
        casinoPnL: parts[3] || '',
        btcPrice: parts[4] ? parseFloat(parts[4]) : null
      };
    });
    
    // Get last game number
    const lastGame = games[games.length - 1];
    return { lastGameNumber: lastGame.gameNumber, games };
  }
  
  // Generate historical games (from inputted game to lastDownloadedGame + 1)
  async function generateHistoricalGames(startingHash, startingGameNumber, downloadedLastGameNumber, downloadedGames) {
    // Calculate how many games to generate
    const targetGameNumber = downloadedLastGameNumber + 1;
    
    if (startingGameNumber <= targetGameNumber) {
      updateHashGenStatus('Input game is older than downloaded!', '#ff3333');
      throw new Error('Starting game number must be newer than downloaded history');
    }
    
    const count = startingGameNumber - targetGameNumber + 1; // +1 to include overlap for verification
    
    console.log(`📝 Generating ${count} games from #${startingGameNumber} to #${targetGameNumber}`);
    updateHashGenStatus(`Generating ${count} games...`, '#ffaa00');
    
    // Initialize trim files
    const trimInitialized = await initializeTrimFiles();
    if (!trimInitialized) {
      throw new Error('Failed to initialize trim files');
    }
    
    let games = [];
    
    const PARALLEL_BATCH_SIZE = 50;
    const HASH_BATCH_SIZE = 1000;
    
    // Phase 1: Generate hash chain
    updateHashGenStatus('Phase 1: Generating hash chain...', '#ffaa00');
    const hashes = [];
    const hashBatches = Math.ceil(count / HASH_BATCH_SIZE);
    
    let currentHash = startingHash;
    
    for (let batch = 0; batch < hashBatches; batch++) {
      const batchStart = batch * HASH_BATCH_SIZE;
      const batchSize = Math.min(HASH_BATCH_SIZE, count - batchStart);
      
      hashes.push(currentHash);
      for (let i = 1; i < batchSize; i++) {
        currentHash = await generatePreviousHash(currentHash);
        hashes.push(currentHash);
      }
      
      const progress = Math.floor(((batch + 1) / hashBatches) * 50);
      const generated = Math.min(batchStart + batchSize, count);
      updateHashGenStatus(`Phase 1: ${generated}/${count} (${progress}%)`, '#ffaa00');
      
      if (batch % 5 === 0 || batch === hashBatches - 1) {
        await new Promise(resolve => setTimeout(resolve, 0));
      }
    }
    
    console.log('✔️ Hash chain generated, calculating multipliers...');
    updateHashGenStatus('Phase 2: Calculating multipliers...', '#00aaff');
    
    // Phase 2: Calculate multipliers
    const totalMultiplierBatches = Math.ceil(count / PARALLEL_BATCH_SIZE);
    let allCalculatedGames = [];
    
    for (let batch = 0; batch < totalMultiplierBatches; batch++) {
      const batchStart = batch * PARALLEL_BATCH_SIZE;
      const batchEnd = Math.min(batchStart + PARALLEL_BATCH_SIZE, count);
      
      const batchPromises = [];
      for (let i = batchStart; i < batchEnd; i++) {
        const gameNumber = startingGameNumber - i;
        const hash = hashes[i];
        
        batchPromises.push(
          calculateMultiplier(hash).then(multiplier => ({
            gameNumber: gameNumber,
            hash: hash,
            crashMultiplier: multiplier,
            duration: null,
            casinoPnL: '',
            btcPrice: null,
            isHistorical: true
          }))
        );
      }
      
      const batchResults = await Promise.all(batchPromises);
      allCalculatedGames.push(...batchResults);
      
      const progress = 50 + Math.floor(((batch + 1) / totalMultiplierBatches) * 50);
      const generated = batchEnd;
      updateHashGenStatus(`Phase 2: ${generated}/${count} (${progress}%)`, '#00aaff');
      
      if (batch % 10 === 0 || batch === totalMultiplierBatches - 1) {
        await new Promise(resolve => setTimeout(resolve, 0));
      }
    }
    
    console.log('✔️ All multipliers calculated, sorting...');
    updateHashGenStatus('Sorting & verifying...', '#00aaff');
    
    // Sort ascending (oldest first)
    allCalculatedGames.sort((a, b) => a.gameNumber - b.gameNumber);
    games = allCalculatedGames;
    
    // VERIFY OVERLAP: Check if our calculated game matches downloaded game at overlap point
    const overlapGameNumber = downloadedLastGameNumber;
    const ourOverlapGame = games.find(g => g.gameNumber === overlapGameNumber);
    const downloadedOverlapGame = downloadedGames.find(g => g.gameNumber === overlapGameNumber);
    
    if (ourOverlapGame && downloadedOverlapGame) {
      const ourMult = ourOverlapGame.crashMultiplier.toFixed(2);
      const downloadedMult = downloadedOverlapGame.crashMultiplier.toFixed(2);
      
      if (ourMult === downloadedMult) {
        console.log(`✅ VERIFICATION SUCCESS: Game #${overlapGameNumber} matches! (${ourMult}x)`);
        updateHashGenStatus(`✅ Verified at #${overlapGameNumber}`, '#00ff00');
      } else {
        console.error(`❌ VERIFICATION FAILED: Game #${overlapGameNumber} mismatch!`);
        console.error(`   Our calculation: ${ourMult}x`);
        console.error(`   Downloaded: ${downloadedMult}x`);
        updateHashGenStatus(`❌ Verification failed!`, '#ff3333');
        throw new Error('Verification failed at overlap point');
      }
    }
    
    return games;
  }
  
  // Write games to trim CSV
  async function writeGamesToTrimCSV(games) {
    if (!trimCsvFileHandle) return;
    
    const writable = await trimCsvFileHandle.createWritable({ keepExistingData: true });
    await writable.seek((await trimCsvFileHandle.getFile()).size);
    
    let buffer = '';
    for (const game of games) {
      const gameNumber = game.gameNumber || '';
      const duration = game.duration !== null && game.duration !== undefined ? game.duration.toFixed(2) : '';
      const multiplier = game.crashMultiplier.toFixed(2);
      const casinoPnL = game.casinoPnL || '';
      const btcPrice = game.btcPrice !== null && game.btcPrice !== undefined ? game.btcPrice.toFixed(2) : '';
      
      buffer += `${gameNumber},${duration},${multiplier},${casinoPnL},${btcPrice}\n`;
    }
    
    await writable.write(buffer);
    await writable.close();
  }
  
  // Merge crash_games into crash_trim
  async function mergeCrashGamesToTrim(historicalEndGameNumber) {
    console.log('🔀 Starting merge of crash_games into crash_trim...');
    mergeInProgress = true;
    updateHashGenStatus('Merging crash_games...', '#ffaa00');
    
    try {
      // Read crash_games.csv
      const csvFile = await csvFileHandle.getFile();
      const csvText = await csvFile.text();
      const lines = csvText.split('\n').filter(line => line.trim());
      
      // Skip header
      const dataLines = lines.slice(1);
      
      console.log(`   Found ${dataLines.length} games in crash_games.csv`);
      
      // Parse and reindex
      let gamesToAppend = [];
      
      for (let i = 0; i < dataLines.length; i++) {
        const line = dataLines[i];
        const parts = line.split(',');
        
        if (parts.length < 10) continue;
        
        const newGameNumber = historicalEndGameNumber + 1 + i;
        const duration = parts[5];
        const multiplier = parts[6];
        const cashedIn = parseFloat(parts[7]) || 0;
        const cashedOut = parseFloat(parts[8]) || 0;
        const btcPrice = parts[9];
        
        const pnl = cashedIn - cashedOut;
        const pnlSign = pnl >= 0 ? '+' : '';
        const casinoPnL = pnlSign + pnl.toFixed(8);
        
        gamesToAppend.push({
          gameNumber: newGameNumber,
          duration: duration ? parseFloat(duration) : null,
          crashMultiplier: parseFloat(multiplier),
          casinoPnL: casinoPnL,
          btcPrice: btcPrice ? parseFloat(btcPrice) : null
        });
      }
      
      // Append merged data to trim
      if (gamesToAppend.length > 0) {
        await writeGamesToTrimCSV(gamesToAppend);
      }
      
      console.log(`✔️ Merged ${dataLines.length} games, reindexed from ${historicalEndGameNumber + 1}`);
      
      const finalGameNumber = historicalEndGameNumber + dataLines.length;
      
      // Process queued games (crashes that happened during merge)
      if (queuedGames.length > 0) {
        console.log(`📥 Processing ${queuedGames.length} queued games...`);
        updateHashGenStatus(`Processing ${queuedGames.length} queued...`, '#ffaa00');
        
        // Sort queued games by detection order to preserve timing
        queuedGames.sort((a, b) => (a.detectionTime || 0) - (b.detectionTime || 0));
        
        for (const game of queuedGames) {
          await logGameDataToTrim(game);
        }
        
        console.log(`✔️ Processed all queued games`);
        queuedGames = [];
      }
      
      useTrimFiles = true;
      mergeInProgress = false;
      
      console.log('✔️ Merge complete, now writing to crash_trim files');
      updateHashGenStatus('✔ Merge complete', '#00ff00');
      
      return finalGameNumber + queuedGames.length;
    } catch (e) {
      console.error('❌ Merge failed:', e);
      mergeInProgress = false;
      throw e;
    }
  }
  
  // Initialize log files
  async function initializeLogFiles() {
    try {
      const dirHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
      window.logDirHandle = dirHandle;
      
      // Delete existing files
      const filesToDelete = ['crash_games.csv', 'crash_trim.csv'];
      
      for (const fileName of filesToDelete) {
        try {
          await dirHandle.removeEntry(fileName);
          console.log(`🗑️ Deleted existing ${fileName}`);
        } catch (e) {}
      }
      
      // Create fresh crash_games.csv
      csvFileHandle = await dirHandle.getFileHandle('crash_games.csv', { create: true });
      
      // Write CSV header
      await writeToCSV('GameNumber,Hash,EventID,StartTime,EndTime,Duration(s),CrashMultiplier,TotalCashedIn_BTC,TotalCashedOut_BTC,BTC_Price_USD\n', false);
      
      console.log('✔️ Log files initialized');
      updateLogStatus('Files Ready', '#00ff00');
      return true;
    } catch (e) {
      console.error('❌ Failed to initialize log files:', e);
      updateLogStatus('Not Setup', '#ff3333');
      return false;
    }
  }
  
  async function initializeTrimFiles() {
    if (!window.logDirHandle) {
      console.error('❌ Directory handle not available');
      return false;
    }
    
    try {
      const dirHandle = window.logDirHandle;
      
      // Delete existing trim file
      try {
        await dirHandle.removeEntry('crash_trim.csv');
        console.log('🗑️ Deleted existing crash_trim.csv');
      } catch (e) {}
      
      // Create fresh trim file
      trimCsvFileHandle = await dirHandle.getFileHandle('crash_trim.csv', { create: true });
      
      // Write trim CSV header
      const trimHeader = 'GameNumber,Duration(s),CrashMultiplier,CasinoPnL_BTC,BTC_Price_USD\n';
      const writable = await trimCsvFileHandle.createWritable();
      await writable.write(trimHeader);
      await writable.close();
      
      console.log('✔️ Trim files initialized');
      return true;
    } catch (e) {
      console.error('❌ Failed to initialize trim files:', e);
      return false;
    }
  }
  
  async function writeToCSV(data, append = true) {
    if (!csvFileHandle) return;
    
    try {
      const writable = await csvFileHandle.createWritable({ keepExistingData: append });
      if (append) {
        await writable.seek((await csvFileHandle.getFile()).size);
      }
      await writable.write(data);
      await writable.close();
    } catch (e) {
      console.error('❌ Failed to write to .csv:', e);
    }
  }
  
  async function logGameDataToTrim(gameData) {
    const gameNumber = gameData.gameNumber || '';
    const duration = gameData.duration !== null && gameData.duration !== undefined ? gameData.duration.toFixed(2) : '';
    const multiplier = gameData.crashMultiplier.toFixed(2);
    
    let casinoPnL = '';
    if (gameData.totalCashedIn !== null && gameData.totalCashedOut !== null) {
      const pnl = gameData.totalCashedIn - gameData.totalCashedOut;
      const pnlSign = pnl >= 0 ? '+' : '';
      casinoPnL = pnlSign + pnl.toFixed(8);
    }
    
    const btcPrice = gameData.btcPrice !== null && gameData.btcPrice !== undefined ? gameData.btcPrice.toFixed(2) : '';
    
    const csvLine = `${gameNumber},${duration},${multiplier},${casinoPnL},${btcPrice}\n`;
    
    if (!trimCsvFileHandle) return;
    
    const writable = await trimCsvFileHandle.createWritable({ keepExistingData: true });
    await writable.seek((await trimCsvFileHandle.getFile()).size);
    await writable.write(csvLine);
    await writable.close();
  }
  
  async function logGameData(gameData) {
    // If merge is in progress, queue this game with timestamp
    if (mergeInProgress) {
      console.log(`⏸️ Merge in progress, queueing game #${gameData.gameNumber}`);
      gameData.detectionTime = Date.now();
      queuedGames.push(gameData);
      return;
    }
    
    if (!window._fileWriteLock) {
      window._fileWriteLock = Promise.resolve();
    }
    
    window._fileWriteLock = window._fileWriteLock.then(async () => {
      if (historicalGamesGenerated || useTrimFiles) {
        await logGameDataToTrim(gameData);
        console.log(`📝 Logged to TRIM: #${gameData.gameNumber} - ${gameData.crashMultiplier.toFixed(2)}x`);
        return;
      }
      
      if (!csvFileHandle) {
        console.log('⏸️ crash_games file not initialized, skipping log');
        return;
      }
      
      const gameNumber = gameData.gameNumber || '';
      const hash = gameData.hash || '';
      const eventId = gameData.eventId || '';
      const startTime = gameData.startTime ? new Date(gameData.startTime).toISOString() : '';
      const endTime = gameData.endTime ? new Date(gameData.endTime).toISOString() : '';
      const duration = gameData.duration !== null && gameData.duration !== undefined ? gameData.duration.toFixed(2) : '';
      const multiplier = gameData.crashMultiplier.toFixed(2);
      const cashedIn = gameData.totalCashedIn !== null ? gameData.totalCashedIn.toFixed(8) : '';
      const cashedOut = gameData.totalCashedOut !== null ? gameData.totalCashedOut.toFixed(8) : '';
      const btcPrice = gameData.btcPrice !== null && gameData.btcPrice !== undefined ? gameData.btcPrice.toFixed(2) : '';
      
      const csvLine = `${gameNumber},${hash},${eventId},${startTime},${endTime},${duration},${multiplier},${cashedIn},${cashedOut},${btcPrice}\n`;
      await writeToCSV(csvLine);
      
      console.log(`📝 Logged to crash_games: #${gameNumber} - ${multiplier}x`);
    }).catch(err => {
      console.error('❌ Error writing game data:', err);
    });
    
    await window._fileWriteLock;
  }
  
  // Create FULL VIEWPORT overlay
  const overlay = document.createElement('div');
  overlay.id = 'crash-multiplier-overlay';
  overlay.innerHTML = `
    <div style="
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      background: rgba(0, 0, 0, 0.98);
      color: #00ff00;
      padding: 40px;
      font-family: 'Courier New', monospace;
      z-index: 999999;
      overflow-y: auto;
      box-sizing: border-box;
    ">
      <div style="max-width: 1200px; margin: 0 auto;">
        <div style="font-size: 24px; color: #00ff00; margin-bottom: 30px; text-align: center; font-weight: bold;">
          🚀 STAKE CRASH MULTIPLIER MONITOR
        </div>
        
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 30px; margin-bottom: 30px;">
          <!-- Current Game Display -->
          <div style="background: #111; padding: 30px; border-radius: 10px; border: 2px solid #00ff00;">
            <div style="font-size: 14px; color: #888; margin-bottom: 10px; text-align: center;">
              CURRENT GAME
            </div>
            <div id="game-number-display" style="font-size: 32px; text-align: center; margin: 10px 0; color: #00aaff;">
              Game #--
            </div>
            <div id="multiplier-display" style="font-size: 64px; text-align: center; margin: 20px 0; font-weight: bold;">
              --
            </div>
            <div style="display: flex; align-items: center; justify-content: center; gap: 8px; margin: 15px 0;">
              <div id="crash-indicator" style="
                width: 15px;
                height: 15px;
                border-radius: 50%;
                background: #333;
                transition: all 0.2s;
              "></div>
              <div id="status-display" style="font-size: 18px; color: #888; text-align: center;">
                Waiting for game...
              </div>
            </div>
          </div>
          
          <!-- Stats Panel -->
          <div style="background: #111; padding: 30px; border-radius: 10px; border: 2px solid #00aaff;">
            <div style="font-size: 14px; color: #888; margin-bottom: 20px; text-align: center;">
              STATISTICS
            </div>
            <div style="font-size: 14px; color: #888; margin: 10px 0;">
              Total Games: <span id="total-games" style="color: #00ff00;">0</span>
            </div>
            <div style="font-size: 14px; color: #888; margin: 10px 0;">
              Historical: <span id="historical-games" style="color: #00aaff;">0</span>
            </div>
            <div style="font-size: 14px; color: #888; margin: 10px 0;">
              BTC Price: $<span id="btc-price" style="color: #ffaa00;">--</span>
            </div>
            <div style="font-size: 14px; color: #888; margin: 10px 0;">
              Messages: <span id="message-count" style="color: #666;">0</span>
            </div>
            <div style="display: flex; align-items: center; gap: 10px; margin: 15px 0;">
              <div id="message-indicator" style="
                width: 15px;
                height: 15px;
                border-radius: 50%;
                background: #333;
                box-shadow: 0 0 5px rgba(0,0,0,0.5);
                transition: all 0.1s;
              "></div>
              <div style="font-size: 12px; color: #888;">Activity</div>
            </div>
          </div>
        </div>
        
        <!-- Hash Generation Section -->
        <div style="background: #111; padding: 30px; border-radius: 10px; margin: 20px 0; border: 2px solid #ffaa00;">
          <div style="font-size: 18px; color: #ffaa00; margin-bottom: 20px; font-weight: bold;">
            📝 GENERATE HISTORICAL GAMES (QUICK MODE)
          </div>
          <div style="font-size: 12px; color: #888; margin-bottom: 15px;">
            This will download pre-generated history from Dropbox and only generate the gap between your input and the downloaded data.
          </div>
          <input id="game-number-input" type="number" placeholder="Enter game number (e.g., 7500500)" min="1" style="
            width: 100%;
            padding: 12px;
            background: #222;
            border: 1px solid #444;
            color: #00ff00;
            font-family: 'Courier New', monospace;
            font-size: 14px;
            border-radius: 5px;
            margin-bottom: 10px;
            box-sizing: border-box;
          "/>
          <input id="hash-input" type="text" placeholder="Enter game hash (64 characters)..." style="
            width: 100%;
            padding: 12px;
            background: #222;
            border: 1px solid #444;
            color: #00ff00;
            font-family: 'Courier New', monospace;
            font-size: 14px;
            border-radius: 5px;
            margin-bottom: 15px;
            box-sizing: border-box;
          "/>
          <button id="generate-btn" style="
            width: 100%;
            padding: 12px;
            background: #222;
            color: #00ff00;
            border: 2px solid #00ff00;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            transition: all 0.2s;
          ">🚀 Generate History</button>
          <div id="hash-gen-status" style="font-size: 12px; color: #666; margin-top: 15px; text-align: center;">
            Ready
          </div>
        </div>
        
        <!-- Logging Section -->
        <div style="background: #111; padding: 30px; border-radius: 10px; margin: 20px 0; border: 2px solid #00aaff;">
          <div style="font-size: 18px; color: #00aaff; margin-bottom: 20px; font-weight: bold;">
            💾 LOGGING CONTROL
          </div>
          <button id="setup-logs-btn" style="
            width: 100%;
            background: #222;
            color: #00aaff;
            border: 2px solid #00aaff;
            padding: 12px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            margin-bottom: 15px;
            transition: all 0.2s;
          ">📁 Setup Log Files</button>
          
          <div style="display: flex; justify-content: space-between; align-items: center; margin: 10px 0;">
            <div style="font-size: 12px; color: #666;">Status:</div>
            <div id="log-status" style="font-size: 12px; color: #666;">Not Setup</div>
          </div>
        </div>
        
        <!-- WebSocket Info -->
        <div style="background: #111; padding: 30px; border-radius: 10px; margin: 20px 0; border: 2px solid #666;">
          <div style="font-size: 18px; color: #888; margin-bottom: 20px; font-weight: bold;">
            🔌 WEBSOCKET CONNECTION
          </div>
          <div id="ws-url-display" style="font-size: 12px; color: #00aaff; margin: 10px 0; word-break: break-all;">
            No WS selected
          </div>
          <div style="margin-top: 20px; display: flex; justify-content: space-between; align-items: center;">
            <button id="switch-ws-btn" style="
              background: #222;
              color: #00ff00;
              border: 2px solid #00ff00;
              padding: 10px 20px;
              border-radius: 5px;
              cursor: pointer;
              font-size: 12px;
              font-family: 'Courier New', monospace;
              transition: all 0.2s;
            ">
              Switch WS [<span id="ws-index">1</span>/<span id="ws-total">0</span>]
            </button>
            <div style="font-size: 12px; color: #666;">
              <span id="ws-status">Waiting...</span>
            </div>
          </div>
        </div>
        
        <!-- Debug section -->
        <div style="background: #111; padding: 20px; border-radius: 10px; border: 1px solid #333;">
          <div style="font-size: 14px; color: #666; margin-bottom: 10px;">DEBUG INFO</div>
          <div id="debug-ws" style="font-size: 11px; color: #666; margin: 5px 0;">WS: 0 | Selected: 0</div>
          <div id="debug-game" style="font-size: 11px; color: #666; margin: 5px 0;">Game: -- | Status: --</div>
          <div id="debug-intercept" style="font-size: 11px; color: #666; margin: 5px 0;">Intercepts: 0</div>
          <div id="debug-listener" style="font-size: 11px; color: #666; margin: 5px 0;">onmessage: 0</div>
          <div id="debug-raw" style="font-size: 11px; color: #666; margin: 5px 0;">Raw msgs: 0</div>
          <div id="debug-parsed" style="font-size: 11px; color: #666; margin: 5px 0;">Parsed: 0</div>
        </div>
      </div>
    </div>
  `;
  
  // Append overlay when DOM is ready
  if (document.body) {
    document.body.appendChild(overlay);
  } else {
    document.addEventListener('DOMContentLoaded', () => {
      document.body.appendChild(overlay);
    });
  }
  
  let messageCount = 0;
  let interceptCount = 0;
  let onmessageCount = 0;
  let rawMessageCount = 0;
  let parsedMessageCount = 0;
  
  // Fetch BTC price periodically
  setInterval(async () => {
    const price = await getBTCPrice();
    if (price) {
      const btcPriceEl = document.getElementById('btc-price');
      if (btcPriceEl) btcPriceEl.textContent = price.toFixed(2);
    }
  }, 60000);
  
  // Initial fetch
  getBTCPrice().then(price => {
    if (price) {
      const btcPriceEl = document.getElementById('btc-price');
      if (btcPriceEl) btcPriceEl.textContent = price.toFixed(2);
    }
  });
  
  function truncateMultiplier(value) {
    return Math.floor(value * 100) / 100;
  }
  
  function updateDebug() {
    const debugWS = document.getElementById('debug-ws');
    const debugGame = document.getElementById('debug-game');
    const debugIntercept = document.getElementById('debug-intercept');
    const debugListener = document.getElementById('debug-listener');
    const debugRaw = document.getElementById('debug-raw');
    const debugParsed = document.getElementById('debug-parsed');
    
    if (debugWS) debugWS.textContent = `WS: ${websocketConnections.length} | Selected: ${currentWebSocketIndex + 1}`;
    if (debugGame) debugGame.textContent = `Game: ${lastGameId ? lastGameId.substring(0, 8) : '--'} | Status: ${gameStatus || '--'}`;
    if (debugIntercept) debugIntercept.textContent = `Intercepts: ${interceptCount}`;
    if (debugListener) debugListener.textContent = `onmessage: ${onmessageCount}`;
    if (debugRaw) debugRaw.textContent = `Raw msgs: ${rawMessageCount}`;
    if (debugParsed) debugParsed.textContent = `Parsed: ${parsedMessageCount}`;
  }
  
  function updateGameCounts() {
    const totalGamesEl = document.getElementById('total-games');
    const historicalGamesEl = document.getElementById('historical-games');
    
    if (totalGamesEl) totalGamesEl.textContent = allGames.length;
    if (historicalGamesEl) {
      const histCount = allGames.filter(g => g.isHistorical).length;
      historicalGamesEl.textContent = histCount;
    }
  }
  
  function updateLogStatus(text, color = '#666') {
    const logStatus = document.getElementById('log-status');
    if (logStatus) {
      logStatus.textContent = text;
      logStatus.style.color = color;
    }
  }
  
  function updateHashGenStatus(text, color = '#666') {
    const status = document.getElementById('hash-gen-status');
    if (status) {
      status.textContent = text;
      status.style.color = color;
    }
  }
  
  function updateWSUrlDisplay() {
    const urlDisplay = document.getElementById('ws-url-display');
    if (urlDisplay && websocketConnections.length > 0) {
      const currentWS = websocketConnections[currentWebSocketIndex];
      if (currentWS) {
        const url = currentWS.url;
        let identifier = url;
        
        if (url.includes('?')) {
          const params = url.split('?')[1];
          identifier = `WS ${currentWebSocketIndex + 1}: ${url.split('?')[0].split('/').pop()}?${params}`;
        } else {
          identifier = `WS ${currentWebSocketIndex + 1}: ${url}`;
        }
        
        urlDisplay.textContent = identifier.length > 80 ? identifier.substring(0, 80) + '...' : identifier;
        urlDisplay.title = `Full URL: ${url}`;
      }
    }
  }
  
  function flashMessageIndicator() {
    const indicator = document.getElementById('message-indicator');
    if (indicator) {
      indicator.style.background = '#00ff00';
      indicator.style.boxShadow = '0 0 10px #00ff00';
      
      setTimeout(() => {
        indicator.style.background = '#333';
        indicator.style.boxShadow = '0 0 5px rgba(0,0,0,0.5)';
      }, 100);
    }
  }
  
  function updateMultiplierDisplay(multiplier, status) {
    const display = document.getElementById('multiplier-display');
    const statusDisplay = document.getElementById('status-display');
    const crashIndicator = document.getElementById('crash-indicator');
    const gameNumberDisplay = document.getElementById('game-number-display');
    
    if (!display) return;
    
    const truncated = truncateMultiplier(multiplier);
    
    // Update game number display
    if (gameNumberDisplay) {
      gameNumberDisplay.textContent = `Game #${nextGameNumber}`;
    }
    
    if (status === 'in_progress') {
      display.textContent = truncated.toFixed(2) + 'x';
      display.style.color = '#00ff00';
      display.style.textShadow = '0 0 15px #00ff00';
      if (statusDisplay) {
        statusDisplay.textContent = '🚀 LIVE';
        statusDisplay.style.color = '#00ff00';
      }
      if (crashIndicator) {
        crashIndicator.style.background = '#00ff00';
        crashIndicator.style.boxShadow = '0 0 15px #00ff00';
      }
    } else if (status === 'crash') {
      display.textContent = truncated.toFixed(2) + 'x';
      display.style.color = '#ff3333';
      display.style.textShadow = '0 0 15px #ff3333';
      if (statusDisplay) {
        statusDisplay.textContent = '💥 CRASHED!';
        statusDisplay.style.color = '#ff3333';
      }
      if (crashIndicator) {
        crashIndicator.style.background = '#ff3333';
        crashIndicator.style.boxShadow = '0 0 20px #ff3333';
      }
    } else if (status === 'starting' || status === 'pending' || status === 'start') {
      display.textContent = '1.00x';
      display.style.color = '#ffaa00';
      display.style.textShadow = '0 0 15px #ffaa00';
      
      if (statusDisplay) {
        if (status === 'starting') {
          statusDisplay.textContent = '⏳ STARTING...';
        } else if (status === 'pending') {
          statusDisplay.textContent = '⏳ PENDING...';
        } else if (status === 'start') {
          statusDisplay.textContent = '⏳ START';
        }
        statusDisplay.style.color = '#ffaa00';
      }
      if (crashIndicator) {
        crashIndicator.style.background = '#ffaa00';
        crashIndicator.style.boxShadow = '0 0 15px #ffaa00';
      }
    }
  }
  
  function resetDisplay() {
    const display = document.getElementById('multiplier-display');
    const status = document.getElementById('status-display');
    const crashIndicator = document.getElementById('crash-indicator');
    if (display) {
      display.textContent = '--';
      display.style.color = '#888';
      display.style.textShadow = 'none';
    }
    if (status) {
      status.textContent = 'Waiting for next game...';
      status.style.color = '#888';
    }
    if (crashIndicator) {
      crashIndicator.style.background = '#333';
      crashIndicator.style.boxShadow = 'none';
    }
  }
  
  function updateMessageCount() {
    const msgCount = document.getElementById('message-count');
    if (msgCount) {
      msgCount.textContent = messageCount;
    }
  }
  
  function updateWSStatus(text, color = '#666') {
    const wsStatus = document.getElementById('ws-status');
    if (wsStatus) {
      wsStatus.textContent = text;
      wsStatus.style.color = color;
    }
  }
  
  function updateWSCount() {
    const wsTotal = document.getElementById('ws-total');
    const wsIndex = document.getElementById('ws-index');
    if (wsTotal) wsTotal.textContent = websocketConnections.length;
    if (wsIndex) wsIndex.textContent = currentWebSocketIndex + 1;
  }
  
  async function aggregateCashedIn(cashedInArray) {
    let totalBTC = 0;
    const btcPrice = await getBTCPrice();
    
    for (const bet of cashedInArray) {
      if (bet.btcAmount) {
        totalBTC += bet.btcAmount;
      } else if (bet.amount && bet.currency && btcPrice) {
        const btcAmount = await convertToBTC(bet.amount, bet.currency, btcPrice);
        if (btcAmount) totalBTC += btcAmount;
      }
    }
    return totalBTC;
  }
  
  async function aggregateCashedOut(cashedOutArray) {
    let totalBTC = 0;
    const btcPrice = await getBTCPrice();
    
    for (const cashout of cashedOutArray) {
      if (cashout.btcAmount) {
        totalBTC += cashout.btcAmount;
      } else if (cashout.amount && cashout.currency && btcPrice) {
        const btcAmount = await convertToBTC(cashout.amount, cashout.currency, btcPrice);
        if (btcAmount) totalBTC += btcAmount;
      }
    }
    return totalBTC;
  }
  
  async function processMessage(messageData, wsIndex) {
    if (wsIndex !== currentWebSocketIndex) {
      return;
    }
    
    messageCount++;
    flashMessageIndicator();
    updateMessageCount();
    
    try {
      const data = JSON.parse(messageData);
      parsedMessageCount++;
      
      if (data.payload && data.payload.data && data.payload.data.crash && data.payload.data.crash.event) {
        const event = data.payload.data.crash.event;
        const status = event.status;
        const gameId = event.id;
        
        console.log(`📊 Status: ${status}, GameID: ${gameId ? gameId.substring(0, 8) : 'N/A'}, Multiplier: ${event.multiplier}`);
        
        if (gameId && gameId !== lastGameId) {
          lastGameId = gameId;
          console.log('🎮 New game:', gameId.substring(0, 8));
          
          const btcPrice = await getBTCPrice();
          
          currentGameData = {
            gameNumber: nextGameNumber,
            eventId: gameId,
            startTime: null,
            endTime: null,
            crashMultiplier: null,
            totalCashedIn: 0,
            totalCashedOut: 0,
            hash: null,
            btcPrice: btcPrice,
            isHistorical: false
          };
        }
        
        gameStatus = status;
        
        if (status === 'in_progress') {
          if (event.multiplier !== null && event.multiplier !== undefined) {
            currentMultiplier = event.multiplier;
            lastMultiplier = event.multiplier;
            
            if (!currentGameData.startTime && event.startTime) {
              currentGameData.startTime = event.startTime;
            }
            
            if (event.cashedOut && event.cashedOut.length > 0) {
              const cashedOutBTC = await aggregateCashedOut(event.cashedOut);
              currentGameData.totalCashedOut += cashedOutBTC;
            }
            
            updateMultiplierDisplay(currentMultiplier, 'in_progress');
            updateWSStatus('Active', '#00ff00');
          }
        } else if (status === 'crash') {
          let crashMultiplier;
          
          if (event.multiplier !== null && event.multiplier !== undefined) {
            crashMultiplier = event.multiplier;
            lastMultiplier = event.multiplier;
          } else if (lastMultiplier !== null && lastMultiplier !== undefined) {
            crashMultiplier = lastMultiplier;
          } else {
            crashMultiplier = 1.00;
            console.log('⚠️ No multiplier found - defaulting to 1.00x (instant crash)');
          }
          
          currentGameData.crashMultiplier = truncateMultiplier(crashMultiplier);
          currentGameData.endTime = event.timestamp;
          
          if (!currentGameData.startTime) {
            currentGameData.startTime = event.timestamp;
            console.log('⚠️ No start time found - using crash timestamp for 1.00x crash');
          }
          
          if (currentGameData.startTime) {
            const start = new Date(currentGameData.startTime).getTime();
            const end = new Date(currentGameData.endTime).getTime();
            currentGameData.duration = (end - start) / 1000;
          } else {
            currentGameData.duration = 0;
          }
          
          console.log(`💥 CRASH at ${crashMultiplier.toFixed(2)}x`);
          
          currentGameData.gameNumber = nextGameNumber;
          
          allGames.push(currentGameData);
          updateGameCounts();
          
          await logGameData(currentGameData);
          console.log(`✅ Game #${currentGameData.gameNumber} logged successfully`);
          
          nextGameNumber++;
          
          updateMultiplierDisplay(crashMultiplier, 'crash');
          updateWSStatus('Crashed', '#ff3333');
        } else if (status === 'starting') {
          console.log('⏳ Game starting...');
          
          if (event.cashedIn && event.cashedIn.length > 0) {
            const cashedInBTC = await aggregateCashedIn(event.cashedIn);
            currentGameData.totalCashedIn += cashedInBTC;
          }
          
          updateMultiplierDisplay(1.00, 'starting');
          updateWSStatus('Starting', '#ffaa00');
          currentMultiplier = null;
          lastMultiplier = null;
        } else if (status === 'pending') {
          console.log('⏳ Game pending...');
          updateMultiplierDisplay(1.00, 'pending');
          updateWSStatus('Pending', '#ffaa00');
        } else if (status === 'start') {
          console.log('⏳ Game start (0x)...');
          const startMultiplier = event.multiplier !== null && event.multiplier !== undefined ? event.multiplier : 1.00;
          updateMultiplierDisplay(startMultiplier, 'start');
          updateWSStatus('Start', '#ffaa00');
          currentMultiplier = null;
          lastMultiplier = null;
        }
      }
      
    } catch (e) {
      console.error('❌ Failed to parse message:', e);
    }
    
    if (messageCount % 10 === 0) {
      updateDebug();
    }
  }
  
  // UI Event Handlers
  setTimeout(() => {
    const switchBtn = document.getElementById('switch-ws-btn');
    if (switchBtn) {
      switchBtn.addEventListener('click', () => {
        if (websocketConnections.length > 1) {
          const oldIndex = currentWebSocketIndex;
          currentWebSocketIndex = (currentWebSocketIndex + 1) % websocketConnections.length;
          updateWSCount();
          updateWSUrlDisplay();
          updateDebug();
          messageCount = 0;
          updateMessageCount();
          
          gameStatus = null;
          lastMultiplier = null;
          currentMultiplier = null;
          lastGameId = null;
          resetDisplay();
          
          console.log(`🔄 Switched from WS ${oldIndex} to WS ${currentWebSocketIndex}`);
          updateWSStatus('Switched', '#ffaa00');
        } else {
          console.log('⏸️ Only one WebSocket available');
        }
      });
      
      switchBtn.addEventListener('mouseenter', () => {
        switchBtn.style.background = '#333';
      });
      switchBtn.addEventListener('mouseleave', () => {
        switchBtn.style.background = '#222';
      });
    }
    
    const setupLogsBtn = document.getElementById('setup-logs-btn');
    if (setupLogsBtn) {
      setupLogsBtn.addEventListener('click', async () => {
        setupLogsBtn.textContent = 'Setting up...';
        setupLogsBtn.disabled = true;
        
        const success = await initializeLogFiles();
        
        if (success) {
          setupLogsBtn.textContent = '✔ Files Ready';
          setupLogsBtn.style.borderColor = '#00ff00';
          setupLogsBtn.style.color = '#00ff00';
          
          historicalGamesGenerated = false;
          
          const generateBtn = document.getElementById('generate-btn');
          const hashInput = document.getElementById('hash-input');
          const gameNumberInput = document.getElementById('game-number-input');
          
          if (generateBtn) {
            generateBtn.disabled = false;
            generateBtn.textContent = '🚀 Generate History';
            generateBtn.style.borderColor = '#00ff00';
            generateBtn.style.color = '#00ff00';
          }
          if (hashInput) hashInput.disabled = false;
          if (gameNumberInput) gameNumberInput.disabled = false;
          
          updateHashGenStatus('Ready for new location', '#00ff00');
          
          console.log('✔️ New file location set. History generation re-enabled.');
          
          setTimeout(() => {
            setupLogsBtn.textContent = '📁 Setup Log Files';
            setupLogsBtn.disabled = false;
            setupLogsBtn.style.borderColor = '#00aaff';
            setupLogsBtn.style.color = '#00aaff';
          }, 2000);
          
        } else {
          setupLogsBtn.textContent = '📁 Setup Log Files';
          setupLogsBtn.disabled = false;
        }
      });
    }
    
    const generateBtn = document.getElementById('generate-btn');
    const hashInput = document.getElementById('hash-input');
    const gameNumberInput = document.getElementById('game-number-input');
    
    if (generateBtn && hashInput && gameNumberInput) {
      generateBtn.addEventListener('click', async () => {
        const hash = hashInput.value.trim();
        const gameNumber = parseInt(gameNumberInput.value);
        
        if (!hash || hash.length !== 64) {
          updateHashGenStatus('Hash must be 64 chars!', '#ff3333');
          return;
        }
        
        if (!gameNumber || gameNumber < 1) {
          updateHashGenStatus('Invalid game number!', '#ff3333');
          return;
        }
        
        if (historicalGamesGenerated) {
          updateHashGenStatus('Already generated!', '#ff3333');
          return;
        }
        
        generateBtn.disabled = true;
        generateBtn.textContent = 'Generating...';
        hashInput.disabled = true;
        gameNumberInput.disabled = true;
        
        try {
          const startTime = Date.now();
          
          // Step 1: Download Dropbox CSV
          const dropboxCsvText = await downloadDropboxCSV();
          const { lastGameNumber: downloadedLastGame, games: downloadedGames } = parseCSVAndGetLastGame(dropboxCsvText);
          
          console.log(`✔️ Downloaded history up to game #${downloadedLastGame}`);
          updateHashGenStatus(`Downloaded up to #${downloadedLastGame}`, '#00aaff');
          
          // Step 2: Write downloaded games to trim file
          await writeGamesToTrimCSV(downloadedGames);
          console.log(`✔️ Wrote ${downloadedGames.length} downloaded games to trim file`);
          
          // Step 3: Generate gap history
          const historicalGames = await generateHistoricalGames(hash, gameNumber, downloadedLastGame, downloadedGames);
          
          // Step 4: Write generated games to trim file
          await writeGamesToTrimCSV(historicalGames);
          console.log(`✔️ Wrote ${historicalGames.length} generated games to trim file`);
          
          const endTime = Date.now();
          const duration = ((endTime - startTime) / 1000).toFixed(1);
          
          console.log(`⏱️ Generation took ${duration}s`);
          
          // Step 5: Merge crash_games data
          console.log('🔀 Starting merge process...');
          const finalGameNumber = await mergeCrashGamesToTrim(gameNumber);
          
          nextGameNumber = finalGameNumber + 1;
          
          const previouslyDetectedGames = allGames.filter(g => !g.isHistorical);
          allGames = [...downloadedGames, ...historicalGames, ...previouslyDetectedGames];
          historicalGamesGenerated = true;
          
          console.log(`✔️ Complete! Next live game will be #${nextGameNumber}`);
          
          updateGameCounts();
          updateHashGenStatus(`✔ Done in ${duration}s`, '#00ff00');
          
          generateBtn.textContent = '✔ Done';
          generateBtn.style.borderColor = '#00ff00';
          generateBtn.style.color = '#00ff00';
          
          console.log(`📊 Total games: ${allGames.length}`);
          console.log(`📝 Now writing live games to crash_trim files`);
        } catch (e) {
          console.error('❌ Failed:', e);
          updateHashGenStatus('Error! ' + e.message, '#ff3333');
          generateBtn.disabled = false;
          generateBtn.textContent = '🚀 Generate History';
          hashInput.disabled = false;
          gameNumberInput.disabled = false;
          mergeInProgress = false;
        }
      });
    }
  }, 1000);
  
  // Override WebSocket constructor
  window.WebSocket = function(url, protocols) {
    const ws = new OriginalWebSocket(url, protocols);
    
    if (websocketConnections.length >= 1) {
      console.log(`⛔ WebSocket limit reached (1/1). Ignoring new WebSocket: ${url}`);
      return ws;
    }
    
    console.log('%c🌐 NEW WEBSOCKET CREATED', 'color: cyan; font-weight: bold;');
    console.log('URL:', url);
    console.log('Protocols:', protocols);
    
    interceptCount++;
    
    const wsIndex = websocketConnections.length;
    websocketConnections.push({
      ws: ws,
      url: url,
      index: wsIndex
    });
    
    currentWebSocketIndex = 0;
    
    updateWSCount();
    updateWSUrlDisplay();
    updateDebug();
    
    console.log(`✔️ WebSocket #${wsIndex} added. Total: ${websocketConnections.length}`);
    console.log(`   URL: ${url}`);
    
    ws.addEventListener('open', () => {
      console.log(`✔️ WebSocket #${wsIndex} OPENED`);
      updateWSStatus('Connected', '#00ff00');
    });
    
    ws.addEventListener('close', () => {
      console.log(`❌ WebSocket #${wsIndex} CLOSED`);
    });
    
    ws.addEventListener('error', (e) => {
      console.log(`⏸️ WebSocket #${wsIndex} ERROR:`, e);
    });
    
    const originalDescriptor = Object.getOwnPropertyDescriptor(OriginalWebSocket.prototype, 'onmessage');
    
    let userOnMessageHandler = null;
    
    Object.defineProperty(ws, 'onmessage', {
      get: function() {
        return userOnMessageHandler;
      },
      set: function(handler) {
        onmessageCount++;
        if (onmessageCount <= 5) {
          updateDebug();
        }
        
        console.log(`%c🎧 onmessage PROPERTY SET on WS #${wsIndex}`, 'color: yellow; font-weight: bold;');
        
        userOnMessageHandler = handler;
        
        const wrappedHandler = function(event) {
          rawMessageCount++;
          
          let result;
          let handlerError = null;
          
          if (userOnMessageHandler) {
            try {
              result = userOnMessageHandler.call(this, event);
            } catch (e) {
              handlerError = e;
            }
          }
          
          try {
            processMessage(event.data, wsIndex);
          } catch (e) {
            // Silent fail
          }
          
          if (rawMessageCount % 10 === 0) {
            updateDebug();
          }
          
          if (handlerError) throw handlerError;
          
          return result;
        };
        
        if (originalDescriptor && originalDescriptor.set) {
          originalDescriptor.set.call(this, wrappedHandler);
        }
      },
      configurable: true,
      enumerable: true
    });
    
    const originalAddEventListener = ws.addEventListener.bind(ws);
    
    ws.addEventListener = function(type, listener, options) {
      if (type === 'message') {
        console.log(`🎧 MESSAGE LISTENER via addEventListener on WS #${wsIndex}`);
        
        const wrappedListener = function(event) {
          rawMessageCount++;
          
          let result;
          try {
            result = listener.apply(this, arguments);
          } catch (e) {
            try {
              processMessage(event.data, wsIndex);
            } catch (monitorError) {
              // Silent fail
            }
            throw e;
          }
          
          try {
            processMessage(event.data, wsIndex);
          } catch (e) {
            // Silent fail
          }
          
          return result;
        };
        
        return originalAddEventListener(type, wrappedListener, options);
      }
      
      return originalAddEventListener(type, listener, options);
    };
    
    return ws;
  };
  
  // Copy all static properties
  window.WebSocket.prototype = OriginalWebSocket.prototype;
  window.WebSocket.CONNECTING = OriginalWebSocket.CONNECTING;
  window.WebSocket.OPEN = OriginalWebSocket.OPEN;
  window.WebSocket.CLOSING = OriginalWebSocket.CLOSING;
  window.WebSocket.CLOSED = OriginalWebSocket.CLOSED;
  
  console.log('%c✔️ WebSocket monitor installed successfully!', 'color: #00ff00; font-size: 14px; font-weight: bold;');
  console.log('Waiting for WebSockets to be created...');
})();