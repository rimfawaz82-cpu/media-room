// كتالوج المتجر: كل شي بيتعدّل من لوحة التحكم (admin.html)
// الترتيب: نسخة لوحة التحكم المحفوظة ← catalog.json (لو موجود) ← القيم الافتراضية هون
export const STORE_KEY = 'cupstudio.catalog.v1';

export const DEFAULT_CATALOG = {
  shop: {
    name: 'كوبي',
    tagline: 'هدية بتحكي عنك',
    currency: '$',
    whatsapp: '96170000000',
    delivery: 3,
  },
  occasions: [
    { id: 'love',  name: 'حب',        emoji: '❤️', cup: '#f6d5dc', box: '#c2405a', ribbon: '#f3c96b', pattern: 'hearts',  text: 'إلك وحدك',    font: 'messiri' },
    { id: 'bday',  name: 'عيد ميلاد', emoji: '🎂', cup: '#fff3d6', box: '#f2a541', ribbon: '#ffffff', pattern: 'confetti', text: 'كل سنة وإنت بخير', font: 'lalezar' },
    { id: 'mom',   name: 'عيد الأم',  emoji: '🌷', cup: '#ffffff', box: '#e8b4c4', ribbon: '#b88a3e', pattern: 'flowers', text: 'ست الحبايب',  font: 'messiri' },
    { id: 'grad',  name: 'تخرّج',     emoji: '🎓', cup: '#1f2a44', box: '#1f2a44', ribbon: '#d4af37', pattern: 'stars',   text: 'مبروك التخرج', font: 'lalezar' },
    { id: 'thanks',name: 'شكر',       emoji: '🤍', cup: '#f4efe6', box: '#7c9a83', ribbon: '#f4efe6', pattern: 'dots',    text: 'شكراً من القلب', font: 'tajawal' },
    { id: 'self',  name: 'لإلي أنا',  emoji: '☕', cup: '#2b2b2b', box: '#d9c3a5', ribbon: '#2b2b2b', pattern: 'none',    text: 'قهوتي أولاً',  font: 'tajawal' },
  ],
  cups: [
    { id: 'mug',    name: 'ماغ كلاسيك',   desc: 'سيراميك ٣٢٠ مل',       price: 8,  shape: 'mug',    badge: 'الأكثر طلباً' },
    { id: 'latte',  name: 'كوب لاتيه',    desc: 'فم عريض ٤٠٠ مل',       price: 10, shape: 'latte',  badge: '' },
    { id: 'travel', name: 'كوب سفر',      desc: 'حراري مع غطا ٤٥٠ مل',  price: 14, shape: 'travel', badge: 'جديد' },
    { id: 'glass',  name: 'كاسة زجاج',    desc: 'زجاج شفاف ٣٥٠ مل',     price: 9,  shape: 'glass',  badge: '' },
  ],
  cupColors: [
    { name: 'أبيض حليبي', hex: '#ffffff' }, { name: 'كريمي', hex: '#f4efe6' },
    { name: 'وردي ناعم', hex: '#f6d5dc' }, { name: 'زهري', hex: '#e8a0b4' },
    { name: 'خوخي', hex: '#f8c9a8' }, { name: 'زبدة', hex: '#fff3d6' },
    { name: 'نعناعي', hex: '#cfe6d8' }, { name: 'سماوي', hex: '#cfe2f3' },
    { name: 'كحلي', hex: '#1f2a44' }, { name: 'أسود مطفي', hex: '#2b2b2b' },
  ],
  fonts: [
    { id: 'messiri', name: 'أنيق',   css: '"El Messiri", serif' },
    { id: 'lalezar', name: 'جريء',   css: '"Lalezar", sans-serif' },
    { id: 'tajawal', name: 'بسيط',   css: '"Tajawal", sans-serif' },
    { id: 'reem',    name: 'يدوي',   css: '"Reem Kufi Fun", sans-serif' },
  ],
  textColors: ['#2b2b2b', '#ffffff', '#c2405a', '#b88a3e', '#1f2a44', '#7c9a83'],
  // pattern: none|hearts|dots|stars|stripes|flowers|confetti — أو image (رفع صورة من لوحة التحكم)
  decorations: [
    { id: 'none',     name: 'بدون',      price: 0, pattern: 'none',     emoji: '○' },
    { id: 'hearts',   name: 'قلوب',      price: 2, pattern: 'hearts',   emoji: '♥' },
    { id: 'flowers',  name: 'ورد',       price: 2, pattern: 'flowers',  emoji: '✿' },
    { id: 'stars',    name: 'نجوم',      price: 2, pattern: 'stars',    emoji: '★' },
    { id: 'dots',     name: 'نقط',       price: 1, pattern: 'dots',     emoji: '●' },
    { id: 'stripes',  name: 'خطوط',      price: 1, pattern: 'stripes',  emoji: '▤' },
    { id: 'confetti', name: 'احتفال',    price: 2, pattern: 'confetti', emoji: '✦' },
  ],
  stickers: [
    { id: 'none',  name: 'بدون',  price: 0, emoji: '' },
    { id: 'heart', name: 'قلب',   price: 1, emoji: '❤️' },
    { id: 'rose',  name: 'وردة',  price: 1, emoji: '🌹' },
    { id: 'crown', name: 'تاج',   price: 1, emoji: '👑' },
    { id: 'cake',  name: 'كيك',   price: 1, emoji: '🎂' },
    { id: 'moon',  name: 'هلال',  price: 1, emoji: '🌙' },
    { id: 'coffee',name: 'قهوة',  price: 1, emoji: '☕' },
  ],
  boxes: [
    { id: 'none', name: 'بدون بوكس', desc: 'الكوب لحاله',          price: 0,  w: 0,  h: 0,  d: 0 },
    { id: 's',    name: 'صغير',      desc: 'الكوب + لمسة',         price: 6,  w: 16, h: 13, d: 16 },
    { id: 'm',    name: 'وسط',       desc: 'الكوب + ٢ إضافات',     price: 10, w: 26, h: 14, d: 18, badge: 'الأفضل قيمة' },
    { id: 'l',    name: 'كبير',      desc: 'الكوب + كل الإضافات',  price: 15, w: 34, h: 15, d: 24 },
  ],
  boxColors: [
    { name: 'خمري', hex: '#c2405a' }, { name: 'زهري', hex: '#e8b4c4' },
    { name: 'كراميل', hex: '#d9c3a5' }, { name: 'زيتي', hex: '#7c9a83' },
    { name: 'كحلي', hex: '#1f2a44' }, { name: 'أسود', hex: '#222222' },
    { name: 'أبيض', hex: '#f7f3ee' }, { name: 'برتقالي', hex: '#f2a541' },
  ],
  ribbons: [
    { id: 'none',  name: 'بدون',   price: 0, hex: '' },
    { id: 'gold',  name: 'ذهبي',   price: 2, hex: '#d4af37' },
    { id: 'white', name: 'أبيض',   price: 1, hex: '#ffffff' },
    { id: 'red',   name: 'أحمر',   price: 1, hex: '#b3122e' },
    { id: 'black', name: 'أسود',   price: 1, hex: '#1a1a1a' },
  ],
  // kind: chocolate|rose|card|candle|teddy|cookies — بيحدد شكلو جوّا البوكس
  addons: [
    { id: 'choco',  name: 'شوكولا فاخرة', price: 6, kind: 'chocolate', emoji: '🍫' },
    { id: 'rose',   name: 'وردة جورية',   price: 4, kind: 'rose',      emoji: '🌹' },
    { id: 'card',   name: 'كرت بخط اليد', price: 2, kind: 'card',      emoji: '💌' },
    { id: 'candle', name: 'شمعة معطّرة',  price: 7, kind: 'candle',    emoji: '🕯️' },
    { id: 'teddy',  name: 'دبدوب صغير',   price: 8, kind: 'teddy',     emoji: '🧸' },
    { id: 'cookie', name: 'كوكيز بيتي',   price: 4, kind: 'cookies',   emoji: '🍪' },
  ],
};

const clone = (o) => JSON.parse(JSON.stringify(o));

export async function loadCatalog() {
  try {
    const saved = localStorage.getItem(STORE_KEY);
    if (saved) return { ...clone(DEFAULT_CATALOG), ...JSON.parse(saved) };
  } catch (e) { /* تخزين مقفول */ }
  try {
    const r = await fetch('catalog.json', { cache: 'no-store' });
    if (r.ok) return { ...clone(DEFAULT_CATALOG), ...(await r.json()) };
  } catch (e) { /* ما في ملف */ }
  return clone(DEFAULT_CATALOG);
}

export function saveCatalog(cat) {
  localStorage.setItem(STORE_KEY, JSON.stringify(cat));
}

export function resetCatalog() {
  try { localStorage.removeItem(STORE_KEY); } catch (e) {}
  return clone(DEFAULT_CATALOG);
}
