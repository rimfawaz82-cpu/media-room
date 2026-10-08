// =====================================================================
//  المرحلة الثانية (لاحقاً): استقبال الشكاوى تلقائياً من WhatsApp Business API
//  هذا الملف جاهز للنشر كـ Supabase Edge Function. لا تحتاجه في المرحلة الأولى.
//
//  المتغيرات المطلوبة (Supabase > Edge Functions > Secrets):
//    WHATSAPP_VERIFY_TOKEN  : كلمة تختارها أنت وتضعها أيضاً في إعدادات Meta
//    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY : متوفرة تلقائياً داخل Supabase
//
//  كل رسالة نصية تصل إلى رقم البلدية تُسجَّل كشكوى "بانتظار التحويل"،
//  ويصل إشعار لمسؤول الشكاوى ليحوّلها إلى القسم المختص.
// =====================================================================
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.45.4';

const db = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!);

Deno.serve(async (req) => {
  const url = new URL(req.url);

  // خطوة التحقق التي تطلبها Meta عند تسجيل الـ Webhook
  if (req.method === 'GET') {
    if (url.searchParams.get('hub.verify_token') === Deno.env.get('WHATSAPP_VERIFY_TOKEN')) {
      return new Response(url.searchParams.get('hub.challenge') ?? '', { status: 200 });
    }
    return new Response('forbidden', { status: 403 });
  }

  if (req.method !== 'POST') return new Response('ok');

  const payload = await req.json().catch(() => ({}));
  for (const entry of payload.entry ?? []) {
    for (const change of entry.changes ?? []) {
      const value = change.value ?? {};
      const contacts = value.contacts ?? [];
      for (const msg of value.messages ?? []) {
        const name = contacts.find((c: any) => c.wa_id === msg.from)?.profile?.name ?? '';
        const body = msg.type === 'text' ? msg.text?.body : `[رسالة من نوع ${msg.type} - راجع واتساب]`;
        const { error } = await db.rpc('ingest_whatsapp_message', {
          p_phone: msg.from, p_name: name, p_body: body ?? '', p_message_id: msg.id
        });
        if (error) console.error(error);
      }
    }
  }
  return new Response('ok');
});
