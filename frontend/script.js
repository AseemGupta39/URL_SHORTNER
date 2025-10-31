// API Configuration
// Automatically detects environment:
// - Development: http://localhost:8000
// - Production: Uses the deployed backend URL
const API_BASE_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8000'  // Development
    : 'https://YOUR_BACKEND_URL.vercel.app';  // TODO: Replace with your actual Vercel backend URL

// Initialize logger (loaded from logger.js)
// Automatically set log level based on environment
if (window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
    LoggerConfig.setLogLevel('INFO');  // Production: Less verbose logs
}

// DOM Elements
const shortenForm = document.getElementById('shortenForm');
const longUrlInput = document.getElementById('longUrl');
const shortenBtn = document.getElementById('shortenBtn');
const loadingDiv = document.getElementById('loading');
const errorDiv = document.getElementById('error');
const errorMessage = document.getElementById('errorMessage');
const resultDiv = document.getElementById('result');
const shortUrlInput = document.getElementById('shortUrl');
const copyBtn = document.getElementById('copyBtn');
const originalUrlSpan = document.getElementById('originalUrl');

// Event Listeners
shortenForm.addEventListener('submit', handleSubmit);
copyBtn.addEventListener('click', handleCopy);

/**
 * Handle form submission
 */
async function handleSubmit(e) {
    e.preventDefault();

    const longUrl = longUrlInput.value.trim();
    logger.debug('Form submitted', { url: longUrl });

    // Validate URL
    if (!isValidUrl(longUrl)) {
        logger.warning('Invalid URL format provided', { url: longUrl });
        showError('Please enter a valid URL (e.g., https://example.com)');
        return;
    }

    logger.debug('URL validation passed, starting shortening process');

    // Reset UI
    hideError();
    hideResult();
    showLoading();
    disableForm();

    try {
        const shortUrl = await shortenUrl(longUrl);
        logger.info('URL shortened successfully', { originalUrl: longUrl, shortUrl });
        showResult(longUrl, shortUrl);
    } catch (error) {
        logger.error('Failed to shorten URL', { error: error.message, url: longUrl });
        showError(error.message);
    } finally {
        hideLoading();
        enableForm();
    }
}

/**
 * Call API to shorten URL
 */
async function shortenUrl(longUrl) {
    logger.debug('Sending API request to shorten URL', { url: longUrl });

    try {
        const response = await fetch(`${API_BASE_URL}/v1/shorten`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ original_url: longUrl })
        });

        logger.debug('Received API response', { status: response.status, ok: response.ok });

        if (!response.ok) {
            const errorData = await response.json();
            logger.error('API returned error response', { status: response.status, detail: errorData.detail });
            throw new Error(errorData.detail || 'Failed to shorten URL');
        }

        const data = await response.json();
        logger.debug('API response parsed successfully', { shortCode: data.short_code });

        // Build the short URL
        // The API returns the short_code, we need to construct the full URL
        const shortUrl = `${API_BASE_URL}/${data.short_code}`;

        return shortUrl;
    } catch (error) {
        if (error.message.includes('fetch')) {
            logger.error('Failed to connect to backend server', { baseUrl: API_BASE_URL });
            throw new Error('Unable to connect to server. Please ensure the backend is running.');
        }
        throw error;
    }
}

/**
 * Handle copy button click
 */
async function handleCopy() {
    const shortUrl = shortUrlInput.value;
    logger.debug('Copy button clicked', { shortUrl });

    try {
        await navigator.clipboard.writeText(shortUrl);
        logger.info('Short URL copied to clipboard', { shortUrl });

        // Visual feedback
        copyBtn.innerHTML = `
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
            </svg>
            Copied!
        `;
        copyBtn.classList.add('copy-success');

        // Reset button after 2 seconds
        setTimeout(() => {
            copyBtn.innerHTML = `
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path>
                </svg>
                Copy
            `;
            copyBtn.classList.remove('copy-success');
        }, 2000);
    } catch (error) {
        logger.error('Failed to copy to clipboard', { error: error.message });
        showError('Failed to copy to clipboard');
    }
}

/**
 * Validate URL format
 */
function isValidUrl(string) {
    try {
        const url = new URL(string);
        return url.protocol === 'http:' || url.protocol === 'https:';
    } catch (_) {
        return false;
    }
}

/**
 * UI Helper Functions
 */
function showLoading() {
    loadingDiv.classList.remove('hidden');
    loadingDiv.classList.add('fade-in');
}

function hideLoading() {
    loadingDiv.classList.add('hidden');
}

function showError(message) {
    errorMessage.textContent = message;
    errorDiv.classList.remove('hidden');
    errorDiv.classList.add('fade-in');
}

function hideError() {
    errorDiv.classList.add('hidden');
}

function showResult(originalUrl, shortUrl) {
    shortUrlInput.value = shortUrl;
    originalUrlSpan.textContent = originalUrl;
    resultDiv.classList.remove('hidden');
    resultDiv.classList.add('fade-in');
}

function hideResult() {
    resultDiv.classList.add('hidden');
}

function disableForm() {
    shortenBtn.disabled = true;
    longUrlInput.disabled = true;
}

function enableForm() {
    shortenBtn.disabled = false;
    longUrlInput.disabled = false;
}

/**
 * Check if backend is reachable on page load
 */
async function checkBackendHealth() {
    logger.info('Application initialized', { sessionId: logger.getSessionId(), apiBaseUrl: API_BASE_URL });
    logger.debug('Checking backend health');

    try {
        const response = await fetch(`${API_BASE_URL}/docs`, { method: 'HEAD' });
        if (!response.ok) {
            logger.warning('Backend health check returned non-OK status', { status: response.status });
        } else {
            logger.info('Backend health check successful', { status: response.status });
        }
    } catch (error) {
        logger.error('Unable to reach backend server', {
            baseUrl: API_BASE_URL,
            error: error.message
        });
        logger.info('Tip: Make sure your backend is running and update API_BASE_URL in script.js');
    }
}

// Check backend health on page load
checkBackendHealth();
