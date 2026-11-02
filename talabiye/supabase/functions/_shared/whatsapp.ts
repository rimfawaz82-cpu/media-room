// =====================================================================
//  أدوات مشتركة: Gemini لفهم الطلبية، وواتساب (Meta Cloud API) للإرسال
// =====================================================================
import { encodeBase64 } from 'jsr:@std/encoding@1/base64';

const GEMINI_KEY = Deno.env.get('GEMINI_API_KEY') ?? '';
const GEMINI_MODEL = Deno.env.get('GEMINI_MODEL') ?? 'gemini-2.5-flash';
const WA_TOKEN = Deno.env.get('WHATSAPP_TOKEN') ?? '';
const WA_PHONE_ID = Deno.env.get('WHATSAPP_PHONE_ID') ?? '';
// نسخة Graph API. Meta بتوقف النسخ القديمة كل فترة، فإذا طلعت أخطاء «version» حدّثيها من الأسرار.
const GRAPH = 'https://graph.facebook.com/' + (Deno.env.get('GRAPH_VERSION') ?? 'v23.0');

export type Order = {
  customer_name?: string;
  items?: { name: string; size?: string; color?: string; qty?: number; price?: number | null }[];
  total?: number | null;
  currency?: string;
  address?: { text?: string; area?: string; building?: string; floor?: string; landmarks?: string[] };
  location?: { lat: number; lng: number } | null;
  delivery_time?: string;
  payment?: string;
  notes?: string;
  missing?: string[];
  done?: boolean;
};

const PROMPT = (shop: string, catalog: string, current: Order) => `إنت مساعد بيستقبل طلبيات عالواتساب لمحل${shop ? ' «' + shop + '»' : ''} بلبنان.
الزبون عم يبعت رسائل أو فويسات باللهجة اللبنانية أو العربي أو الإنكليزي أو مخلوطين.
${catalog ? 'أصناف المحل وأسعارو (استعملها للأسعار والأسماء، وما تبيع شي مش موجود):\n' + catalog + '\n' : ''}
الطلبية لحد هلّق (JSON): ${JSON.stringify(current)}

حدّث الطلبية حسب الرسالة الجديدة: زيد، شيل، أو عدّل. ورجّع JSON بس بهالشكل:
{"order": {"customer_name":"","items":[{"name":"","size":"","color":"","qty":1,"price":null}],"total":null,"currency":"USD","address":{"text":"","area":"","building":"","floor":"","landmarks":[]},"delivery_time":"","payment":"","notes":"","missing":[],"done":false},
 "reply": "الرد عالزبون"}

قواعد:
- ما تخترع شي ما انقال. الأسعار من لائحة المحل بس، وإذا الصنف مش باللائحة، اتركو null وزيدو بـ missing.
- missing: الأشياء الناقصة لتكمل الطلبية (مقاس، لون، كمية، عنوان، طريقة دفع).
- إذا العنوان ناقص أو مش واضح وما في location، اطلب من الزبون يبعت موقعو من زر «الموقع» بالواتساب.
- done = true بس إذا الزبون أكّد إنو خلص وكل الأساسي موجود.
- reply: جملتين أو تلاتة، لطيف، باللهجة اللبنانية. بيأكد اللي فهمتو وبيسأل عن الناقص بس. ما تعطي وعود عن وقت التوصيل أو أسعار مش باللائحة.
- إذا الرسالة مش عن طلبية (سلام، سؤال عام)، رد بلطف بجملة وحدة وخلّي الطلبية متل ما هيي.
- إنت بتحكي بس عن المحل وطلبياتو. إذا سألك الزبون عن شي تاني، قلّو بلطف إنك هون للطلبيات.`;

export async function understand(opts: { shop: string; catalog: string; current: Order; text?: string; audio?: Uint8Array; mime?: string }): Promise<{ order: Order; reply: string }> {
  if (!GEMINI_KEY) throw new Error('GEMINI_API_KEY مش محطوط بالأسرار');
  const parts: unknown[] = [{ text: PROMPT(opts.shop, opts.catalog, opts.current) }];
  if (opts.audio) parts.push({ inline_data: { mime_type: opts.mime || 'audio/ogg', data: encodeBase64(opts.audio) } });
  if (opts.text) parts.push({ text: 'رسالة الزبون الجديدة:\n' + opts.text });
  const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_KEY}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ contents: [{ role: 'user', parts }], generationConfig: { temperature: 0.2, responseMimeType: 'application/json' } }),
  });
  if (!r.ok) throw new Error('Gemini ' + r.status + ': ' + (await r.text()).slice(0, 300));
  const data = await r.json();
  const out = data?.candidates?.[0]?.content?.parts?.map((p: { text?: string }) => p.text ?? '').join('') ?? '';
  const parsed = JSON.parse(out.replace(/^```json\s*|\s*```$/g, ''));
  return { order: parsed.order ?? opts.current, reply: String(parsed.reply ?? '') };
}

// تنزيل فويس أو صورة من واتساب
export async function downloadMedia(mediaId: string): Promise<{ bytes: Uint8Array; mime: string }> {
  const meta = await fetch(`${GRAPH}/${mediaId}`, { headers: { Authorization: 'Bearer ' + WA_TOKEN } });
  if (!meta.ok) throw new Error('media meta ' + meta.status + ': ' + (await meta.text()).slice(0, 200));
  const { url, mime_type } = await meta.json();
  const file = await fetch(url, { headers: { Authorization: 'Bearer ' + WA_TOKEN } });
  if (!file.ok) throw new Error('media file ' + file.status);
  const mime = String(mime_type || 'audio/ogg').split(';')[0];
  return { bytes: new Uint8Array(await file.arrayBuffer()), mime: /opus|ogg/.test(mime) ? 'audio/ogg' : mime };
}

// إرسال رسالة نص (بينفع بس خلال ٢٤ ساعة من آخر رسالة من الزبون)
export async function sendText(to: string, body: string): Promise<{ ok: true; id: string } | { ok: false; error: string }> {
  if (!WA_TOKEN || !WA_PHONE_ID) return { ok: false, error: 'WHATSAPP_TOKEN أو WHATSAPP_PHONE_ID مش محطوطين' };
  const r = await fetch(`${GRAPH}/${WA_PHONE_ID}/messages`, {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + WA_TOKEN, 'Content-Type': 'application/json' },
    body: JSON.stringify({ messaging_product: 'whatsapp', recipient_type: 'individual', to, type: 'text', text: { preview_url: true, body } }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) return { ok: false, error: j?.error?.message || ('HTTP ' + r.status) };
  return { ok: true, id: j?.messages?.[0]?.id ?? '' };
}

// التأكد إنو الطلب جايي من Meta فعلاً (توقيع X-Hub-Signature-256)
export async function validSignature(raw: string, header: string | null): Promise<boolean> {
  const secret = Deno.env.get('WHATSAPP_APP_SECRET') ?? '';
  if (!secret) return true;   // بلا سر ما منقدر نتأكد؛ حطيه قبل ما تفتحي للزبائن
  if (!header?.startsWith('sha256=')) return false;
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(raw)));
  const hex = Array.from(sig, b => b.toString(16).padStart(2, '0')).join('');
  const given = header.slice(7);
  if (given.length !== hex.length) return false;
  let diff = 0; for (let i = 0; i < hex.length; i++) diff |= hex.charCodeAt(i) ^ given.charCodeAt(i);
  return diff === 0;
}
