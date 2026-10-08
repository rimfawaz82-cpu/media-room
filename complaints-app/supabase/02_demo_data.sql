-- =====================================================================
--  الملف 2 من 2: المستخدمون الأوائل + بيانات تجريبية
--  شغّله مرة واحدة فقط بعد الملف 01_schema.sql
--
--  حسابات الدخول التجريبية (غيّر كلمات السر بعد التجربة من شاشة "المستخدمون"):
--    مسؤول الشكاوى : admin   / Admin@2026
--    نائب الرئيس   : deputy  / Deputy@2026
--    دائرة الأشغال : works   / Works@2026
--    المفرزة الصحية: health  / Health@2026
--    دائرة الشرطة  : police  / Police@2026
-- =====================================================================

do $$
declare
  u_admin uuid; u_deputy uuid; u_works uuid; u_health uuid; u_police uuid;
  texts text[] := array[
    'السلام عليكم، في حفرة كبيرة بنص الطريق قدام الفرن، صار في أكتر من حادث موتسيكل. الرجاء المعالجة بأسرع وقت.',
    'النفايات متراكمة عند الحاوية من ٣ أيام والريحة صارت لا تحتمل، والقطط عم تفلّتها عالأرض.',
    'عمود الإنارة مطفي من أسبوعين والشارع عتمة كتير بالليل، الولاد بيخافوا يمشوا.',
    'في مطعم عم يرمي زيت القلي بالمجرور والمجرور فاض عالرصيف.',
    'سيارات مصفوفة صف تاني كل يوم الصبح وما عم نقدر نطلع من الموقف.',
    'مياه آسنة عم تطلع من الريغار بالزاروب وصار في بعوض كتير.',
    'محل خضرة حاطط بضاعته على كامل الرصيف والناس عم تمشي بنص الطريق.',
    'ورشة بناء عم تشتغل بعد نص الليل وفي ضجة كبيرة، وما في أي إذن ظاهر.',
    'كلاب شاردة عم تتجمع قرب المدرسة وفي ولد انعضّ مبارح.',
    'الريغار مكسور وغطاه مش موجود، خطر كتير على المارة.',
    'ملحمة عم تبيع لحمة مكشوفة برّات المحل بالشمس.',
    'مولد اشتراك عم يطلّع دخان أسود كثيف عالبيوت والناس عم تختنق.',
    'شجرة واقعة عالرصيف من العاصفة وسادّة الطريق.',
    'دراجات نارية عم تعمل سباقات بالليل بالشارع العام.',
    'تسرب مياه من خط الشفة الرئيسي والمي عم تمشي بالشارع من يومين.'
  ];
  depts text[] := array['works','works','works','health','police','health','police','police','health','works','health','health','works','police','works'];
  areas text[] := array['المعمورة','صفير','بئر العبد','الرويس','حي الأميركان','السانت تيريز','الكفاءات','وسط حارة حريك'];
  streets text[] := array['قرب الفرن','الشارع العام','مقابل المدرسة','زاروب الجامع','قرب الصيدلية','طلعة المستشفى','جنب محطة البنزين','خلف السوبرماركت'];
  names text[] := array['حسين','فاطمة','علي','زينب','محمد','مريم','حسن','نور','أحمد',''];
  pr text[] := array['normal','normal','urgent','normal','emergency','normal','urgent','normal'];
  i int; cid bigint; d text; d2 text; ts timestamptz; st text; ser text; seen_t timestamptz;
  start_t timestamptz; close_t timestamptz; seen_user uuid; yr int := extract(year from now())::int;
  aid bigint;
begin
  if exists (select 1 from public.profiles where username = 'admin') then
    raise notice 'البيانات التجريبية موجودة مسبقاً - لم يتم إضافة شيء';
    return;
  end if;

  u_admin  := public._create_auth_user('admin',  'Admin@2026');
  u_deputy := public._create_auth_user('deputy', 'Deputy@2026');
  u_works  := public._create_auth_user('works',  'Works@2026');
  u_health := public._create_auth_user('health', 'Health@2026');
  u_police := public._create_auth_user('police', 'Police@2026');
  insert into public.profiles (id, username, full_name, role, department_id) values
    (u_admin,  'admin',  'مسؤول الشكاوى',            'admin',      null),
    (u_deputy, 'deputy', 'نائب الرئيس',              'deputy',     null),
    (u_works,  'works',  'مسؤول دائرة الأشغال',       'department', 'works'),
    (u_health, 'health', 'مسؤول المفرزة الصحية',      'department', 'health'),
    (u_police, 'police', 'مسؤول دائرة الشرطة',        'department', 'police');

  -- 30 شكوى موزعة على آخر 40 يوماً بحالات مختلفة
  for i in 1..30 loop
    ts := now() - make_interval(days => (40 - i - (i % 3)), hours => (i * 7) % 24);
    if i >= 28 then ts := now() - make_interval(hours => (31 - i) * 3); end if;  -- 3 شكاوى من اليوم
    d := depts[1 + (i - 1) % 15];
    ser := yr::text || '-' || lpad(i::text, 4, '0');
    insert into public.complaints (serial, year, seq, body, citizen_name, citizen_phone, area, address, priority, created_by, created_at, updated_at)
    values (ser, yr, i, texts[1 + (i - 1) % 15],
            names[1 + i % 10], case when i % 4 = 0 then '' else '03' || lpad(((i * 7919) % 1000000)::text, 6, '0') end,
            areas[1 + i % 8], streets[1 + (i * 3) % 8], pr[1 + i % 8], u_admin, ts, ts)
    returning id into cid;
    insert into public.events (complaint_id, actor_id, actor_name, action, details, created_at)
    values (cid, u_admin, 'مسؤول الشكاوى', 'إنشاء الشكوى', 'رقم ' || ser, ts);

    -- بعض الشكاوى لأكثر من قسم
    d2 := case when i % 7 = 0 then (case when d = 'police' then 'works' else 'police' end) else null end;

    foreach d in array array_remove(array[d, d2], null) loop
      -- اختيار الحالة حسب عمر الشكوى
      st := case
        when i >= 28 then 'new'
        when i in (24, 26) then 'new'               -- متأخرة: لم تُشاهد خلال 24 ساعة
        when i % 6 = 0 then 'failed'
        when i < 20 then 'resolved'
        when i % 2 = 0 then 'in_progress'
        else 'seen' end;
      seen_user := case d when 'works' then u_works when 'health' then u_health else u_police end;
      seen_t  := ts + make_interval(hours => 2 + i % 9);
      start_t := seen_t + make_interval(hours => 3);
      close_t := start_t + make_interval(days => 1 + i % 5, hours => i % 11);

      insert into public.assignments (complaint_id, department_id, status, assigned_at, assigned_by,
        seen_at, seen_by, started_at, closed_at, closed_by, result)
      values (cid, d, st, ts, u_admin,
        case when st <> 'new' then seen_t end, case when st <> 'new' then seen_user end,
        case when st in ('in_progress', 'resolved', 'failed') then start_t end,
        case when st in ('resolved', 'failed') then close_t end,
        case when st in ('resolved', 'failed') then seen_user end,
        case st when 'resolved' then 'تم الكشف على المكان ومعالجة المشكلة بالكامل، والوضع طبيعي حالياً.'
                when 'failed' then 'المكان ملك خاص ويحتاج إلى إذن قضائي، تم إبلاغ صاحب العلاقة.' end)
      returning id into aid;

      insert into public.events (complaint_id, department_id, actor_id, actor_name, action, details, created_at)
      values (cid, null, u_admin, 'مسؤول الشكاوى', 'تحويل الشكوى', 'إلى: ' || public._dept_name(d), ts + interval '1 minute');
      insert into public.notifications (user_id, complaint_id, title, body, created_at, read_at)
      values (seen_user, cid, 'شكوى جديدة رقم ' || ser, left(texts[1 + (i - 1) % 15], 120), ts,
              case when st <> 'new' then seen_t end);

      if st <> 'new' then
        insert into public.complaint_views (complaint_id, user_id, first_viewed_at, last_viewed_at)
        values (cid, seen_user, seen_t, seen_t) on conflict do nothing;
        insert into public.events (complaint_id, department_id, actor_id, actor_name, action, details, created_at)
        values (cid, d, seen_user, (select full_name from public.profiles where id = seen_user), 'تمت المشاهدة', public._dept_name(d), seen_t);
      end if;
      if st in ('in_progress', 'resolved', 'failed') then
        insert into public.events (complaint_id, department_id, actor_id, actor_name, action, details, created_at)
        values (cid, d, seen_user, (select full_name from public.profiles where id = seen_user), 'بدء المتابعة', public._dept_name(d), start_t);
        insert into public.notes (complaint_id, department_id, author_id, kind, body, created_at)
        values (cid, d, seen_user, 'followup', 'تم إرسال فريق للكشف على المكان.', start_t);
        insert into public.events (complaint_id, department_id, actor_id, actor_name, action, details, created_at)
        values (cid, d, seen_user, (select full_name from public.profiles where id = seen_user), 'ملاحظة متابعة',
                public._dept_name(d) || ': تم إرسال فريق للكشف على المكان.', start_t + interval '1 minute');
      end if;
      if st in ('resolved', 'failed') then
        insert into public.events (complaint_id, department_id, actor_id, actor_name, action, details, created_at)
        values (cid, d, seen_user, (select full_name from public.profiles where id = seen_user),
                case st when 'resolved' then 'تمت المعالجة' else 'تعذّرت المعالجة' end,
                public._dept_name(d) || ': ' || (select result from public.assignments where id = aid), close_t);
      end if;
    end loop;

    -- نائب الرئيس اطّلع على بعض الشكاوى وأعطى توجيهات
    if i % 3 = 0 then
      update public.complaints set deputy_seen_at = ts + interval '5 hours', deputy_seen_by = u_deputy where id = cid;
      insert into public.complaint_views (complaint_id, user_id, first_viewed_at, last_viewed_at)
      values (cid, u_deputy, ts + interval '5 hours', ts + interval '5 hours');
      insert into public.events (complaint_id, actor_id, actor_name, action, internal, created_at)
      values (cid, u_deputy, 'نائب الرئيس', 'اطّلع عليها نائب الرئيس', true, ts + interval '5 hours');
    end if;
    if i % 9 = 0 then
      insert into public.notes (complaint_id, author_id, kind, body, created_at)
      values (cid, u_deputy, 'directive', 'يرجى إعطاء هذه الشكوى الأولوية وإبلاغي بالنتيجة.', ts + interval '6 hours');
      insert into public.events (complaint_id, actor_id, actor_name, action, details, created_at)
      values (cid, u_deputy, 'نائب الرئيس', 'توجيه من نائب الرئيس', 'يرجى إعطاء هذه الشكوى الأولوية وإبلاغي بالنتيجة.', ts + interval '6 hours');
    end if;

    perform public._refresh_complaint_state(cid);
    update public.complaints c set closed_at = (select max(closed_at) from public.assignments a where a.complaint_id = c.id)
     where c.id = cid and c.closed_at is not null;
  end loop;

  raise notice 'تمت إضافة المستخدمين و30 شكوى تجريبية';
end $$;
