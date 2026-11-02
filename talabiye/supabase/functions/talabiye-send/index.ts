// =====================================================================
//  طلبيّة: بيبعت الرد اللي وافقتي عليه من صندوق الطلبيات
//
//  النشر: supabase functions deploy talabiye-send
//  (بلا --no-verify-jwt: لازم تكوني مسجّلة دخول)
//  الطلب: POST { order_id, text }
// =====================================================================
import { createClient } from 'npm:@supabase/supabase-js@2.45.4';
import { sendText } from '../_shared/whatsapp.ts';

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, apikey, content-type, x-client-info',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};
const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { ...CORS, 'Content-Type': 'application/json' } });

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  if (req.method !== 'POST') return json({ error: 'POST only' }, 405);

  // منقرا بصلاحيات المستخدم نفسو: إذا مش عضو، ما بيشوف الطلبية
  const user = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_ANON_KEY')!, {
    global: { headers: { Authorization: req.headers.get('Authorization') ?? '' } },
  });
  const { order_id, text } = await req.json().catch(() => ({}));
  const body = String(text ?? '').trim();
  if (!order_id || !body) return json({ error: 'ناقص order_id أو النص' }, 400);
  if (body.length > 4000) return json({ error: 'الرسالة طويلة كتير' }, 400);

  const { data: order, error } = await user.from('wa_orders').select('id, phone, name, last_in_at').eq('id', order_id).maybeSingle();
  if (error || !order) return json({ error: 'ما لقينا الطلبية أو ما عندك صلاحية' }, 403);

  // واتساب ما بيسمح برسالة عادية بعد ٢٤ ساعة من آخر رسالة من الزبون
  if (Date.now() - new Date(order.last_in_at).getTime() > 24 * 3600_000) {
    return json({ error: 'مرق أكتر من ٢٤ ساعة على آخر رسالة من الزبون. واتساب ما بيسمح بالرد إلا برسالة جاهزة (template).' }, 409);
  }

  const admin = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!);
  const sent = await sendText(order.phone, body);
  if (!sent.ok) {
    await admin.from('wa_orders').update({ reply_status: 'failed', reply_error: sent.error }).eq('id', order.id);
    return json({ error: sent.error }, 502);
  }
  await admin.from('wa_messages').insert({ wa_id: sent.id || null, phone: order.phone, name: order.name, direction: 'out', type: 'text', body, order_id: order.id });
  await admin.from('wa_orders').update({ reply: body, reply_status: 'sent', reply_error: '' }).eq('id', order.id);
  return json({ ok: true });
});
