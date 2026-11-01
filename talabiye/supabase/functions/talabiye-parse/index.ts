// =====================================================================
//  طلبيّة: بتحوّل فويس أو محادثة واتساب لطلبية مرتّبة (Gemini)
//
//  النشر (مرة وحدة):
//    supabase functions deploy talabiye-parse --no-verify-jwt
//  الأسرار (Supabase > Edge Functions > Secrets):
//    GEMINI_API_KEY : مفتاح Google AI Studio
//    GEMINI_MODEL   : اختياري، الافتراضي gemini-2.5-flash
//
//  الطلب:  POST { audio?: base64, mime?: string, text?: string }
//  الرد:   { order: {...} }  أو  { error: string }
// =====================================================================

const KEY = Deno.env.get('GEMINI_API_KEY') ?? '';
const MODEL = Deno.env.get('GEMINI_MODEL') ?? 'gemini-2.5-flash';
const MAX_AUDIO_B64 = 8 * 1024 * 1024;   // ~6MB صوت = فويس طويل كتير
const MAX_TEXT = 12000;
const PER_IP_PER_HOUR = 40;               // حماية بسيطة للتجربة المجانية

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'content-type, authorization, apikey, x-client-info',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};

const hits = new Map<string, number[]>();
function limited(ip: string) {
  const now = Date.now(), hour = 3600_000;
  const list = (hits.get(ip) ?? []).filter(t => now - t < hour);
  list.push(now);
  hits.set(ip, list);
  return list.length > PER_IP_PER_HOUR;
}

const PROMPT = `إنت مساعد لبيّاع أونلاين بلبنان. رح يوصلك فويس نوت أو محادثة واتساب من زبون، باللهجة اللبنانية أو بالعربي أو الإنكليزي أو مخلوطين.
استخرج الطلبية ورجّع JSON بس، بهالشكل بالظبط:
{
  "customer_name": "" ,
  "phone": "",
  "items": [{"name": "", "size": "", "color": "", "qty": 1, "price": null}],
  "total": null,
  "currency": "USD أو LBP أو فاضي",
  "address": {
    "text": "العنوان متل ما قالو الزبون، مرتّب بجملة وحدة",
    "city": "",
    "area": "",
    "street": "",
    "building": "",
    "floor": "",
    "landmarks": ["معالم قريبة متل فرن، جامع، صيدلية..."],
    "map_query": "أفضل نص للبحث عالخريطة: اسم معلم أو شارع + المنطقة + Lebanon"
  },
  "delivery_time": "",
  "payment": "كاش عالتسليم، Whish، OMT... أو فاضي",
  "notes": "",
  "missing": ["الأشياء الناقصة اللي لازم البيّاع يسألها: مقاس، لون، رقم، عنوان أوضح..."],
  "reply": "رسالة قصيرة ولطيفة باللهجة اللبنانية من البيّاع للزبون: بتأكد الطلبية وبتسأل عن الناقص بس"
}
قواعد:
- ما تخترع شي ما انقال. إذا شي مش معروف خليه فاضي أو null وحطّو بـ missing إذا مهم.
- الأسعار أرقام بس. "مية" = 100، "خمسين ألف" = 50000 ليرة.
- إذا في أكتر من قطعة، كل وحدة لحالها.
- reply بلا إيموجي كتير، جملتين أو تلاتة.`;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { ...CORS, 'Content-Type': 'application/json' } });
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  if (req.method !== 'POST') return json({ error: 'POST only' }, 405);
  if (!KEY) return json({ error: 'GEMINI_API_KEY مش محطوط بالأسرار' }, 500);

  const ip = req.headers.get('x-forwarded-for')?.split(',')[0].trim() ?? 'x';
  if (limited(ip)) return json({ error: 'كتير طلبات. جرّب بعد شوي.' }, 429);

  const body = await req.json().catch(() => ({}));
  const audio: string = typeof body.audio === 'string' ? body.audio : '';
  const text: string = typeof body.text === 'string' ? body.text.slice(0, MAX_TEXT) : '';
  if (!audio && !text.trim()) return json({ error: 'ابعت فويس أو نص' }, 400);
  if (audio.length > MAX_AUDIO_B64) return json({ error: 'الفويس طويل كتير' }, 413);

  const parts: unknown[] = [{ text: PROMPT }];
  if (audio) parts.push({ inline_data: { mime_type: String(body.mime || 'audio/ogg'), data: audio } });
  if (text.trim()) parts.push({ text: 'المحادثة:\n' + text });

  const r = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent?key=${KEY}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{ role: 'user', parts }],
        generationConfig: { temperature: 0.2, responseMimeType: 'application/json' },
      }),
    },
  );
  if (!r.ok) {
    console.error(r.status, await r.text());
    return json({ error: 'الذكاء الاصطناعي ما ردّ. جرّب كمان مرة.' }, 502);
  }
  const data = await r.json();
  const out = data?.candidates?.[0]?.content?.parts?.map((p: any) => p.text ?? '').join('') ?? '';
  try {
    return json({ order: JSON.parse(out.replace(/^```json\s*|\s*```$/g, '')) });
  } catch {
    console.error('bad json', out);
    return json({ error: 'ما قدرت إفهم الطلبية. جرّب فويس أوضح.' }, 422);
  }
});
