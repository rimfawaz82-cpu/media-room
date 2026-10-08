// =====================================================================
//  إعدادات الاتصال بقاعدة البيانات
//  ضع هنا القيمتين من Supabase:  Project Settings > API
//  (مفتاح anon public آمن للنشر، فالحماية مطبّقة داخل قاعدة البيانات)
// =====================================================================
window.APP_CONFIG = {
  SUPABASE_URL: 'https://XXXXXXXX.supabase.co',
  SUPABASE_ANON_KEY: 'ضع-مفتاح-anon-public-هنا',

  // لا تغيّره إلا إذا غيّرت login_domain في قاعدة البيانات
  LOGIN_DOMAIN: 'harethreik.app'
};
