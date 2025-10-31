/**
 * Frontend Logger Utility
 *
 * Provides structured, colored logging similar to backend Python logger.
 *
 * Features:
 * - Colored console output with log levels
 * - Session ID tracking (one ID per page load, tracks entire user journey)
 * - Formatted timestamps
 * - Configurable log level
 * - Function name tracking for better debugging
 *
 * Usage:
 *   logger.debug('User clicked button', { buttonId: 'submit' });
 *   logger.info('URL shortened successfully', { shortCode: 'abc123' });
 *   logger.warning('Invalid URL format');
 *   logger.error('API request failed', { error: err.message });
 */

// Log Levels (same as Python logging)
const LogLevel = {
    DEBUG: 10,
    INFO: 20,
    WARNING: 30,
    ERROR: 40,
    CRITICAL: 50
};

// Log Level Names
const LogLevelNames = {
    10: 'DEBUG',
    20: 'INFO',
    30: 'WARNING',
    40: 'ERROR',
    50: 'CRITICAL'
};

// Console colors (using browser console styling)
const LogColors = {
    DEBUG: '#6B7280',    // Gray
    INFO: '#3B82F6',     // Blue
    WARNING: '#F59E0B',  // Orange
    ERROR: '#EF4444',    // Red
    CRITICAL: '#DC2626'  // Dark Red
};

// Configuration
class LoggerConfig {
    static LOG_LEVEL = LogLevel.DEBUG;  // Change to INFO in production
    static ENABLE_SESSION_ID = true;
    static SESSION_ID = LoggerConfig.generateSessionId();

    /**
     * Generate a unique session ID (12 characters, like backend request ID)
     * This ID persists for the entire page session (until page refresh)
     */
    static generateSessionId() {
        return 'xxxxxxxx-xxxx'.replace(/x/g, () => {
            return Math.floor(Math.random() * 16).toString(16);
        });
    }

    /**
     * Set log level from string
     * Usage: LoggerConfig.setLogLevel('INFO') for production
     */
    static setLogLevel(levelName) {
        const level = LogLevel[levelName.toUpperCase()];
        if (level !== undefined) {
            this.LOG_LEVEL = level;
        } else {
            console.warn(`Invalid log level: ${levelName}. Using DEBUG.`);
        }
    }
}

/**
 * Logger Class
 */
class Logger {
    constructor() {
        this.sessionId = LoggerConfig.SESSION_ID;
    }

    /**
     * Format timestamp (HH:MM:SS format)
     */
    _formatTimestamp() {
        const now = new Date();
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');
        const seconds = String(now.getSeconds()).padStart(2, '0');
        return `${hours}:${minutes}:${seconds}`;
    }

    /**
     * Get caller function name (for location tracking)
     */
    _getCallerInfo() {
        try {
            const stack = new Error().stack;
            // Parse stack trace to get caller function
            // Stack format: "at functionName (file:line:col)"
            const lines = stack.split('\n');
            // Skip: Error, _getCallerInfo, _log, and the log level method
            const callerLine = lines[4] || lines[3] || 'unknown';

            // Extract function name or mark as anonymous
            const match = callerLine.match(/at (\w+)/);
            return match ? match[1] : 'anonymous';
        } catch {
            return 'unknown';
        }
    }

    /**
     * Core logging method
     */
    _log(level, message, data = null) {
        // Check if this log level should be output
        if (level < LoggerConfig.LOG_LEVEL) {
            return;
        }

        const timestamp = this._formatTimestamp();
        const levelName = LogLevelNames[level];
        const color = LogColors[levelName];
        const caller = this._getCallerInfo();

        // Session ID (12 chars like backend request ID)
        const sessionIdStr = LoggerConfig.ENABLE_SESSION_ID
            ? `[${this.sessionId}]`
            : '';

        // Build log message similar to backend format:
        // LEVEL | TIMESTAMP | [SESSION_ID] | LOCATION | MESSAGE
        const logParts = [
            `%c${levelName}%c`,
            '|',
            timestamp
        ];

        const styles = [
            `color: ${color}; font-weight: bold`,  // Level color
            ''  // Reset style
        ];

        if (sessionIdStr) {
            logParts.push('|', sessionIdStr);
        }

        logParts.push('|', `${caller}()`);
        logParts.push('|');
        logParts.push(`%c${message}%c`);

        // Add color to message
        styles.push(`color: ${color}`, '');

        const formattedMessage = logParts.join(' ');

        // Choose appropriate console method
        const consoleMethod = level >= LogLevel.ERROR ? 'error' :
                            level >= LogLevel.WARNING ? 'warn' :
                            'log';

        // Log the formatted message
        console[consoleMethod](formattedMessage, ...styles);

        // If data is provided, log it separately
        if (data !== null && data !== undefined) {
            console[consoleMethod]('  └─ Data:', data);
        }
    }

    /**
     * Log at DEBUG level
     * Use for: Intermediate steps, validation checks, state changes
     */
    debug(message, data = null) {
        this._log(LogLevel.DEBUG, message, data);
    }

    /**
     * Log at INFO level
     * Use for: Successful operations, completed actions
     */
    info(message, data = null) {
        this._log(LogLevel.INFO, message, data);
    }

    /**
     * Log at WARNING level
     * Use for: Expected failures, validation errors, recoverable issues
     */
    warning(message, data = null) {
        this._log(LogLevel.WARNING, message, data);
    }

    /**
     * Log at ERROR level
     * Use for: API failures, unexpected errors, operation failures
     */
    error(message, data = null) {
        this._log(LogLevel.ERROR, message, data);
    }

    /**
     * Log at CRITICAL level
     * Use for: Fatal errors, application-breaking issues
     */
    critical(message, data = null) {
        this._log(LogLevel.CRITICAL, message, data);
    }

    /**
     * Get current session ID
     */
    getSessionId() {
        return this.sessionId;
    }
}

// Create singleton instance
const logger = new Logger();

// Export for use in other files
// For browsers without module support, attach to window
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { logger, LoggerConfig, LogLevel };
} else {
    window.logger = logger;
    window.LoggerConfig = LoggerConfig;
    window.LogLevel = LogLevel;
}

// Log startup message to verify logger is loaded
console.log('[Logger] Frontend logger loaded successfully');
console.log('[Logger] Session ID:', logger.getSessionId());
console.log('[Logger] Log level:', LogLevelNames[LoggerConfig.LOG_LEVEL]);
