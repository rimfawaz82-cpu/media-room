// =====================================================================
//  طلبيّة: مساعد واتساب. بيستقبل رسائل الزبائن من Meta
//
//  النشر:  supabase functions deploy talabiye-whatsapp --no-verify-jwt
//  الأسرار (Edge Functions > Secrets):
//    WHATSAPP_VERIFY_TOKEN : كلمة بتختاريها وبتحطيها كمان بإعدادات Webhook عند Meta
//    WHATSAPP_APP_SECRET   : App secret من إعدادات تطبيق Meta (للتأكد إنو الرسائل من Meta)
//    WHATSAPP_TOKEN        : توكن الوصول (System User token)
//    WHATSAPP_PHONE_ID     : Phone number ID
//    GEMINI_API_KEY        : مفتاح Google AI Studio
//    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY : موجودين لحالهن
//
//  رابط الـ Webhook: https://<project>.supabase.co/functions/v1/talabiye-whatsapp
//  واشتركي بحقل "messages".
// =====================================================================
import { createClient } from 'npm:@supabase/supabase-js@2.45.4';
import { downloadMedia, Order, sendText, understand, validSignature } from '../_shared/whatsapp.ts';

const db = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!);
const OPEN_HOURS = 24;   // رسالة جديدة بعد هالمدة بتفتح طلبية جديدة

type WaMessage = {
  id: string; from: string; type: string; timestamp?: string;
  text?: { body: string };
  audio?: { id: string; mime_type?: string };
  image?: { id: string; caption?: string };
  location?: { latitude: number; longitude: number; name?: string; address?: string };
  interactive?: unknown; button?: { text?: string };
};

async function settings() {
  const { data } = await db.from('talabiye_settings').select('shop_name, auto_reply, catalog').eq('id', 1).maybeSingle();
  return data ?? { shop_name: '', auto_reply: false, catalog: '' };
}

async function openOrder(phone: string, name: string) {
  const since = new Date(Date.now() - OPEN_HOURS * 3600_000).toISOString();
  const { data } = await db.from('wa_orders').select('*')
    .eq('phone', phone).eq('status', 'draft').gte('last_in_at', since)
    .order('updated_at', { ascending: false }).limit(1).maybeSingle();
  if (data) return data;
  const { data: created, error } = await db.from('wa_orders').insert({ phone, name }).select('*').single();
  if (error) throw error;
  return created;
}

async function handle(msg: WaMessage, name: string) {
  // منمنع معالجة نفس الرسالة مرتين (Meta بتعيد الإرسال إذا تأخرنا)
  const body = msg.text?.body ?? msg.image?.caption ?? msg.button?.text
    ?? (msg.location ? `📍 ${msg.location.latitude},${msg.location.longitude} ${msg.location.name ?? ''} ${msg.location.address ?? ''}`.trim() : '')
    ?? '';
  const { error: dup } = await db.from('wa_messages').insert({ wa_id: msg.id, phone: msg.from, name, direction: 'in', type: msg.type, body });
  if (dup) { if (dup.code === '23505') return; throw dup; }

  const s = await settings();
  const order = await openOrder(msg.from, name);
  await db.from('wa_messages').update({ order_id: order.id }).eq('wa_id', msg.id);
  const current: Order = order.data ?? {};

  let next: Order = current, reply = '';
  if (msg.type === 'location' && msg.location) {
    // الدبّوس من زر «الموقع» بالواتساب: منحطو بالطلبية مباشرة
    next = { ...current, location: { lat: msg.location.latitude, lng: msg.location.longitude },
      missing: (current.missing ?? []).filter(m => !/عنوان|موقع|location/i.test(m)) };
    if (msg.location.address) next.address = { ...(current.address ?? {}), text: msg.location.address };
    reply = 'وصل موقعك، شكراً! 📍';
  } else if (msg.type === 'audio' && msg.audio) {
    const media = await downloadMedia(msg.audio.id);
    ({ order: next, reply } = await understand({ shop: s.shop_name, catalog: s.catalog, current, audio: media.bytes, mime: media.mime }));
  } else if (msg.type === 'text' || msg.type === 'button' || (msg.type === 'image' && msg.image?.caption)) {
    ({ order: next, reply } = await understand({ shop: s.shop_name, catalog: s.catalog, current, text: body }));
  } else {
    // صورة بلا كلام، ملصق، ...: منخليها للمحل يشوفها
    await db.from('wa_orders').update({ last_in_at: new Date().toISOString(), name: name || order.name }).eq('id', order.id);
    return;
  }

  const patch = { data: next, reply, reply_status: reply ? 'pending' : 'none', reply_error: '', last_in_at: new Date().toISOString(), name: name || order.name };
  await db.from('wa_orders').update(patch).eq('id', order.id);

  if (s.auto_reply && reply) {
    const sent = await sendText(msg.from, reply);
    if (sent.ok) {
      await db.from('wa_messages').insert({ wa_id: sent.id || null, phone: msg.from, name, direction: 'out', type: 'text', body: reply, order_id: order.id });
      await db.from('wa_orders').update({ reply_status: 'sent' }).eq('id', order.id);
    } else {
      await db.from('wa_orders').update({ reply_status: 'failed', reply_error: sent.error }).eq('id', order.id);
    }
  }
}

async function process(payload: any) {
  for (const entry of payload.entry ?? []) {
    for (const change of entry.changes ?? []) {
      const value = change.value ?? {};
      const contacts = value.contacts ?? [];
      for (const msg of (value.messages ?? []) as WaMessage[]) {
        const name = contacts.find((c: any) => c.wa_id === msg.from)?.profile?.name ?? '';
        try { await handle(msg, name); }
        catch (e) {
          console.error('handle', msg.id, e);
          await db.from('wa_orders').update({ reply_status: 'failed', reply_error: String((e as Error)?.message ?? e).slice(0, 300) })
            .eq('phone', msg.from).eq('status', 'draft');
        }
      }
      // value.statuses (انبعتت، انقرت...) ما منحتاجها هلّق
    }
  }
}

Deno.serve(async (req) => {
  const url = new URL(req.url);
  if (req.method === 'GET') {
    if (url.searchParams.get('hub.mode') === 'subscribe' && url.searchParams.get('hub.verify_token') === Deno.env.get('WHATSAPP_VERIFY_TOKEN')) {
      return new Response(url.searchParams.get('hub.challenge') ?? '', { status: 200 });
    }
    return new Response('forbidden', { status: 403 });
  }
  if (req.method !== 'POST') return new Response('ok');

  const raw = await req.text();
  if (!(await validSignature(raw, req.headers.get('x-hub-signature-256')))) return new Response('bad signature', { status: 401 });
  let payload: unknown;
  try { payload = JSON.parse(raw); } catch { return new Response('ok'); }

  // منرد عـ Meta فوراً، والتحليل بيكمّل بالخلفية (Gemini بياخد كم ثانية)
  const work = process(payload);
  // deno-lint-ignore no-explicit-any
  const rt = (globalThis as any).EdgeRuntime;
  if (rt?.waitUntil) rt.waitUntil(work); else await work;
  return new Response('ok');
});
