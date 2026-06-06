import fs from 'fs';
import os from 'os';
import path from 'path';
import util from 'util';

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const LEVEL_PRIORITY: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
};

let configured = false;
let logFile = '';
let fileLevel: LogLevel = 'info';

function resolveLogFile(): string {
  if (process.env.OSTWIN_BOT_LOG_FILE) return process.env.OSTWIN_BOT_LOG_FILE;
  const home = process.env.OSTWIN_HOME || path.join(os.homedir(), '.ostwin');
  return path.join(home, 'bot', 'debug.log');
}

function resolveLevel(): LogLevel {
  const raw = (process.env.OSTWIN_BOT_LOG_LEVEL || process.env.OSTWIN_LOG_LEVEL || 'info').toLowerCase();
  if (raw === 'debug' || raw === 'info' || raw === 'warn' || raw === 'error') return raw;
  return 'info';
}

function shouldWrite(level: LogLevel): boolean {
  return LEVEL_PRIORITY[level] >= LEVEL_PRIORITY[fileLevel];
}

function formatLine(level: LogLevel, args: unknown[]): string {
  const message = util.format(...args);
  return `${new Date().toISOString()}  ${level.toUpperCase().padEnd(5)}  ${message}\n`;
}

function append(level: LogLevel, args: unknown[]): void {
  if (!configured || !shouldWrite(level)) return;
  try {
    fs.appendFileSync(logFile, formatLine(level, args), 'utf8');
  } catch {
    // Logging must never crash the bot.
  }
}

export function setupBotLogging(): string {
  if (configured) return logFile;
  logFile = resolveLogFile();
  fileLevel = resolveLevel();
  fs.mkdirSync(path.dirname(logFile), { recursive: true });

  const originalLog = console.log.bind(console);
  const originalInfo = console.info.bind(console);
  const originalWarn = console.warn.bind(console);
  const originalError = console.error.bind(console);
  const originalDebug = console.debug.bind(console);

  console.log = (...args: unknown[]) => { append('info', args); originalLog(...args); };
  console.info = (...args: unknown[]) => { append('info', args); originalInfo(...args); };
  console.warn = (...args: unknown[]) => { append('warn', args); originalWarn(...args); };
  console.error = (...args: unknown[]) => { append('error', args); originalError(...args); };
  console.debug = (...args: unknown[]) => { append('debug', args); originalDebug(...args); };

  configured = true;
  console.log(`[BOT] Log file: ${logFile} (level=${fileLevel.toUpperCase()})`);
  return logFile;
}

export function logBotDebug(message: string, context?: Record<string, unknown>): void {
  if (context) console.debug(`${message} ${JSON.stringify(context)}`);
  else console.debug(message);
}

export function logBotInfo(message: string, context?: Record<string, unknown>): void {
  if (context) console.log(`${message} ${JSON.stringify(context)}`);
  else console.log(message);
}

setupBotLogging();
