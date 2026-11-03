// ES9-P-15 时间展示工具：存储层为 UTC，展示层统一换算北京时间（Asia/Shanghai）。
// 页面新增时间列请优先使用 fmtDateTime / fmtDate，避免散落 toLocaleString()（依赖浏览器本地时区）。

const TZ = 'Asia/Shanghai';

const dateTimeFmt = new Intl.DateTimeFormat('zh-CN', {
  timeZone: TZ,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

const dateFmt = new Intl.DateTimeFormat('zh-CN', {
  timeZone: TZ,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

function toDate(value) {
  if (value instanceof Date) return value;
  if (typeof value === 'number') return new Date(value);
  if (typeof value === 'string' && value) return new Date(value);
  return null;
}

/** zh-parts 数组 → "YYYY-MM-DD HH:mm:ss"（北京时间） */
function parts(partsArr) {
  const map = Object.fromEntries(partsArr.map((p) => [p.type, p.value]));
  return `${map.year}-${map.month}-${map.day} ${map.hour === '24' ? '00' : map.hour}:${map.minute}:${map.second}`;
}

/**
 * 格式化为北京时间日期时间串。
 * @param {Date|string|number|null|undefined} value ISO 串 / Date / 时间戳
 * @param {string} fallback 空值或非法值时的占位（默认 '—'）
 * @returns {string} 如 "2026-01-02 00:00:00"
 */
export function fmtDateTime(value, fallback = '—') {
  const d = toDate(value);
  if (!d || Number.isNaN(d.getTime())) return fallback;
  return parts(dateTimeFmt.formatToParts(d));
}

/**
 * 格式化为北京时间日期串（不含时分秒）。
 * @param {Date|string|number|null|undefined} value
 * @param {string} fallback
 * @returns {string} 如 "2026-01-02"
 */
export function fmtDate(value, fallback = '—') {
  const d = toDate(value);
  if (!d || Number.isNaN(d.getTime())) return fallback;
  const map = Object.fromEntries(dateFmt.formatToParts(d).map((p) => [p.type, p.value]));
  return `${map.year}-${map.month}-${map.day}`;
}

/** 北京时间日期时间 + (UTC+8) 脚注，用于报告/表头等需要显式标注时区的场合。 */
export function fmtDateTimeUtc8(value, fallback = '—') {
  const s = fmtDateTime(value, null);
  return s == null ? fallback : `${s} (UTC+8)`;
}

export { TZ as BEIJING_TZ };
