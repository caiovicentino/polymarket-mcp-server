/**
 * Polymarket MCP Dashboard - Main JavaScript
 *
 * Provides interactive functionality for the dashboard including:
 * - Real-time updates via WebSocket
 * - Notifications
 * - Utility functions
 * - API communication
 */

// ============================================================================
// Notification System
// ============================================================================

let notificationTimeout = null;

/**
 * Show notification message
 * @param {string} message - The message to display
 * @param {string} type - Type: 'success', 'error', 'warning', 'info'
 */
function showNotification(message, type = 'info') {
    // Remove existing notification
    const existing = document.querySelector('.notification');
    if (existing) {
        existing.remove();
    }

    // Clear existing timeout
    if (notificationTimeout) {
        clearTimeout(notificationTimeout);
    }

    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;

    // Add to DOM
    document.body.appendChild(notification);

    // Auto-remove after 5 seconds
    notificationTimeout = setTimeout(() => {
        notification.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => {
            notification.remove();
        }, 300);
    }, 5000);
}

// ============================================================================
// HTML Escaping
// ============================================================================

/**
 * Escape HTML-significant characters (& < > " ') for safe interpolation
 * into innerHTML and attributes.
 *
 * Frontend-only defense: the API keeps returning raw text (contract pin),
 * so every render site that interpolates external data MUST route it
 * through esc(). Note that esc() protects innerHTML/text nodes and static
 * attribute values, but NOT onclick="...${...}" -- the attribute is decoded
 * before the JS parser sees it; those sites use event delegation instead
 * (data-action/data-market-id).
 * @param {*} value - Value to escape (coerced to string)
 * @returns {string} Escaped string
 */
function esc(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#x27;');
}

// ============================================================================
// Formatting Utilities
// ============================================================================

/**
 * Format number with commas
 * @param {number} num - Number to format
 * @returns {string} Formatted number
 */
function formatNumber(num) {
    if (num === null || num === undefined) return '0';
    num = Number(num);
    return num.toLocaleString('en-US', {
        maximumFractionDigits: 0
    });
}

/**
 * Format currency (USD)
 * @param {number} amount - Amount to format
 * @returns {string} Formatted currency
 */
function formatCurrency(amount) {
    if (amount === null || amount === undefined) return '$0';
    amount = Number(amount);
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
    }).format(amount);
}

/**
 * Format price (0-1 range as percentage)
 * @param {number} price - Price to format
 * @returns {string} Formatted price
 */
function formatPrice(price) {
    if (price === null || price === undefined) return 'N/A';
    price = Number(price);
    return `${(price * 100).toFixed(1)}%`;
}

/**
 * Format percentage
 * @param {number} value - Value to format (0-1 range)
 * @returns {string} Formatted percentage
 */
function formatPercent(value) {
    if (value === null || value === undefined) return '0%';
    return `${(value * 100).toFixed(2)}%`;
}

/**
 * Format timestamp to relative time
 * @param {string|Date} timestamp - Timestamp to format
 * @returns {string} Relative time string
 */
function formatRelativeTime(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);

    if (seconds < 60) return 'Just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)} minutes ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} hours ago`;
    return `${Math.floor(seconds / 86400)} days ago`;
}

// ============================================================================
// API Communication
// ============================================================================

/**
 * Generic API request handler
 * @param {string} endpoint - API endpoint
 * @param {object} options - Fetch options
 * @returns {Promise} API response
 */
async function apiRequest(endpoint, options = {}) {
    try {
        const response = await fetch(endpoint, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            },
            ...options,
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Request failed');
        }

        return await response.json();
    } catch (error) {
        console.error('API request failed:', error);
        throw error;
    }
}

/**
 * Get MCP status
 * @returns {Promise} Status data
 */
/**
 * Extract market rows from a /api/markets response in either wire state:
 * a bare array (pre-wrap routes) or the {"markets": [...]} envelope
 * (T-0307 wrap). Returns [] for error envelopes and garbage so callers
 * fall through to their empty-state handling.
 */
function marketRowsOf(data) {
    if (Array.isArray(data)) return data;
    if (data && Array.isArray(data.markets)) return data.markets;
    return [];
}

async function getMCPStatus() {
    return apiRequest('/api/status');
}

/**
 * Test MCP connection
 * @returns {Promise} Test result
 */
async function testMCPConnection() {
    return apiRequest('/api/test-connection');
}

/**
 * Get trending markets
 * @param {number} limit - Number of markets to fetch
 * @returns {Promise} Markets data
 */
async function getTrendingMarkets(limit = 10) {
    return apiRequest(`/api/markets/trending?limit=${limit}`);
}

/**
 * Search markets
 * @param {string} query - Search query
 * @param {number} limit - Number of results
 * @returns {Promise} Search results
 */
async function searchMarkets(query, limit = 20) {
    return apiRequest(`/api/markets/search?q=${encodeURIComponent(query)}&limit=${limit}`);
}

/**
 * Get market details
 * @param {string} marketId - Market ID
 * @returns {Promise} Market details
 */
async function getMarketDetails(marketId) {
    return apiRequest(`/api/markets/${encodeURIComponent(marketId)}`);
}

/**
 * Analyze market
 * @param {string} marketId - Market ID
 * @returns {Promise} Analysis result
 */
async function analyzeMarket(marketId) {
    return apiRequest(`/api/markets/${encodeURIComponent(marketId)}/analyze`);
}

/**
 * Update configuration
 * @param {object} config - Configuration object
 * @returns {Promise} Update result
 */
async function updateConfiguration(config) {
    return apiRequest('/api/config', {
        method: 'POST',
        body: JSON.stringify(config),
    });
}

/**
 * Get dashboard statistics
 * @returns {Promise} Statistics data
 */
async function getDashboardStats() {
    return apiRequest('/api/stats');
}

// ============================================================================
// WebSocket Management
// ============================================================================

let ws = null;
let wsReconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAY = 5000;

/**
 * Initialize WebSocket connection
 */
function initializeWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('WebSocket connected');
        wsReconnectAttempts = 0;
        updateWebSocketStatus(true);
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected');
        updateWebSocketStatus(false);
        attemptReconnect();
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        updateWebSocketStatus(false);
    };

    ws.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            handleWebSocketMessage(message);
        } catch (error) {
            console.error('Failed to parse WebSocket message:', error);
        }
    };
}

/**
 * Handle WebSocket messages
 * @param {object} message - Message from server
 */
function handleWebSocketMessage(message) {
    switch (message.type) {
        case 'status':
            console.log('Status update:', message.data);
            break;

        case 'stats_update':
            updateDashboardStats(message.data);
            break;

        case 'market_update':
            handleMarketUpdate(message.data);
            break;

        case 'notification':
            showNotification(message.data.message, message.data.type);
            break;

        default:
            console.log('Unknown message type:', message.type);
    }
}

/**
 * Update WebSocket connection status indicator
 * @param {boolean} connected - Connection status
 */
function updateWebSocketStatus(connected) {
    const statusEl = document.getElementById('ws-status');
    if (statusEl) {
        statusEl.textContent = connected ? 'Connected' : 'Disconnected';
        statusEl.className = connected ? 'text-success' : 'text-error';
    }
}

/**
 * Attempt to reconnect WebSocket
 */
function attemptReconnect() {
    if (wsReconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        console.log('Max reconnection attempts reached');
        return;
    }

    wsReconnectAttempts++;
    console.log(`Reconnection attempt ${wsReconnectAttempts}/${MAX_RECONNECT_ATTEMPTS}`);

    setTimeout(() => {
        initializeWebSocket();
    }, RECONNECT_DELAY);
}

/**
 * Update dashboard statistics from WebSocket
 * @param {object} data - Stats data
 */
function updateDashboardStats(data) {
    if (data.stats) {
        // Update stats displays if elements exist
        const elements = {
            'total-requests': data.stats.requests_total,
            'api-calls': data.stats.api_calls,
            'markets-viewed': data.stats.markets_viewed,
            'errors': data.stats.errors,
        };

        Object.entries(elements).forEach(([id, value]) => {
            const el = document.getElementById(id);
            if (el) {
                el.textContent = value;
            }
        });

        // Update last updated timestamp
        const lastUpdatedEl = document.getElementById('last-updated');
        if (lastUpdatedEl) {
            lastUpdatedEl.textContent = new Date().toLocaleTimeString();
        }
    }
}

/**
 * Handle market update from WebSocket
 * @param {object} data - Market data
 */
function handleMarketUpdate(data) {
    // Refresh markets if on markets page
    if (window.location.pathname === '/markets') {
        console.log('Market update received:', data);
        // Could update specific market row here
    }
}

// ============================================================================
// Local Storage Utilities
// ============================================================================

/**
 * Save data to local storage
 * @param {string} key - Storage key
 * @param {*} value - Value to store
 */
function saveToStorage(key, value) {
    try {
        localStorage.setItem(key, JSON.stringify(value));
    } catch (error) {
        console.error('Failed to save to storage:', error);
    }
}

/**
 * Load data from local storage
 * @param {string} key - Storage key
 * @param {*} defaultValue - Default value if not found
 * @returns {*} Stored value or default
 */
function loadFromStorage(key, defaultValue = null) {
    try {
        const item = localStorage.getItem(key);
        return item ? JSON.parse(item) : defaultValue;
    } catch (error) {
        console.error('Failed to load from storage:', error);
        return defaultValue;
    }
}

// ============================================================================
// Debounce Utility
// ============================================================================

/**
 * Debounce function calls
 * @param {Function} func - Function to debounce
 * @param {number} wait - Wait time in ms
 * @returns {Function} Debounced function
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// ============================================================================
// Copy to Clipboard
// ============================================================================

/**
 * Copy text to clipboard
 * @param {string} text - Text to copy
 */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showNotification('Copied to clipboard!', 'success');
    } catch (error) {
        console.error('Failed to copy:', error);
        showNotification('Failed to copy to clipboard', 'error');
    }
}

// ============================================================================
// Theme Management
// ============================================================================

/**
 * Toggle dark/light theme
 */
function toggleTheme() {
    const html = document.documentElement;
    const currentTheme = html.classList.contains('dark') ? 'dark' : 'light';
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

    html.classList.remove(currentTheme);
    html.classList.add(newTheme);

    saveToStorage('theme', newTheme);
    showNotification(`Theme changed to ${newTheme}`, 'info');
}

/**
 * Load saved theme preference
 */
function loadThemePreference() {
    const savedTheme = loadFromStorage('theme', 'dark');
    document.documentElement.classList.add(savedTheme);
}

// ============================================================================
// Error Handling
// ============================================================================

/**
 * Global error handler
 */
window.addEventListener('error', (event) => {
    console.error('Global error:', event.error);
    showNotification('An unexpected error occurred', 'error');
});

/**
 * Unhandled promise rejection handler
 */
window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled promise rejection:', event.reason);
    showNotification('An unexpected error occurred', 'error');
});

// ============================================================================
// Event Delegation (XSS-safe dynamic action buttons)
// ============================================================================

/**
 * Delegated click handler for dynamically-rendered action buttons.
 *
 * Buttons carry data-action ("analyze" | "details") and data-market-id
 * (HTML-escaped at render time via esc(); the browser decodes the attribute
 * value before dataset reads it, so dataset.marketId is the raw id).
 * Delegation replaces interpolated inline onclick="fn('${id}')" attributes,
 * which HTML-escaping alone cannot make safe.
 */
document.body.addEventListener('click', (event) => {
    const actionEl = event.target.closest('[data-action]');
    if (!actionEl) return;
    const marketId = actionEl.dataset.marketId;
    if (!marketId) return;

    if (actionEl.dataset.action === 'analyze' && typeof window.analyzeMarket === 'function') {
        window.analyzeMarket(marketId);
    } else if (actionEl.dataset.action === 'details' && typeof window.viewDetails === 'function') {
        window.viewDetails(marketId);
    }
});

// ============================================================================
// Initialization
// ============================================================================

// Load theme preference on startup
document.addEventListener('DOMContentLoaded', () => {
    loadThemePreference();
    console.log('Dashboard initialized');
});

// Export functions for use in inline scripts
window.showNotification = showNotification;
window.esc = esc;
window.formatNumber = formatNumber;
window.formatCurrency = formatCurrency;
window.formatPrice = formatPrice;
window.formatPercent = formatPercent;
window.formatRelativeTime = formatRelativeTime;
window.copyToClipboard = copyToClipboard;
window.toggleTheme = toggleTheme;
