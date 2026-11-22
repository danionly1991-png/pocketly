-- Spec 04: get_month_analytics(), everything the analytics page needs in one round trip.
-- security invoker: RLS on expenses/categories applies as the calling user (auth.uid()).
-- Money is returned as text (exact numeric, never a JSON float).

create or replace function public.get_month_analytics(p_month_start date, p_today date)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_uid         uuid := (select auth.uid());
  v_current     date;
  v_first       date;
  v_month       date;
  v_month_end   date;
  v_is_current  boolean;
  v_days_in     integer;
  v_days        integer;   -- days_elapsed
  v_to          date;      -- last counted day of the selected month
  v_prev        date;
  v_prev_end    date;
  v_prev_days   integer;
  v_window_end  date;
  v_six_from    date;
  v_total       numeric;
  v_count       bigint;
  v_prev_window numeric;
  v_prev_full   numeric;
  v_prev_count  bigint;
begin
  if v_uid is null then
    raise exception 'not_authenticated' using errcode = '42501';
  end if;
  if p_today is null then
    raise exception 'p_today_required' using errcode = '22004';
  end if;

  v_current := date_trunc('month', p_today::timestamp)::date;

  -- First available month: the same rule as dashboard_totals().first_month.
  v_first := date_trunc('month', least(
    (select min(e.spent_on) from public.expenses e where e.user_id = v_uid),
    (select (min(c.created_at) at time zone 'Asia/Karachi')::date
       from public.categories c where c.user_id = v_uid),
    p_today
  )::timestamp)::date;

  -- Out-of-range month -> current month. Flask already rejects bad formats and future months.
  v_month := date_trunc('month', coalesce(p_month_start, v_current)::timestamp)::date;
  if v_month < v_first or v_month > v_current then
    v_month := v_current;
  end if;

  v_month_end  := (v_month + interval '1 month')::date - 1;
  v_is_current := v_month = v_current;
  v_days_in    := extract(day from v_month_end)::integer;
  v_days       := case when v_is_current then extract(day from p_today)::integer else v_days_in end;
  v_to         := v_month + (v_days - 1);

  v_prev       := (v_month - interval '1 month')::date;
  v_prev_end   := v_month - 1;
  v_prev_days  := extract(day from v_prev_end)::integer;
  v_window_end := case when v_is_current
                       then v_prev + (least(v_days, v_prev_days) - 1)
                       else v_prev_end end;
  v_six_from   := greatest((v_month - interval '5 months')::date, v_first);

  select coalesce(sum(e.amount), 0), count(*)
    into v_total, v_count
    from public.expenses e
   where e.user_id = v_uid and e.spent_on between v_month and v_to;

  select coalesce(sum(e.amount) filter (where e.spent_on <= v_window_end), 0),
         coalesce(sum(e.amount), 0),
         count(*)
    into v_prev_window, v_prev_full, v_prev_count
    from public.expenses e
   where e.user_id = v_uid and e.spent_on between v_prev and v_prev_end;

  return jsonb_build_object(
    'month',            to_char(v_month, 'YYYY-MM'),
    'first_month',      to_char(v_first, 'YYYY-MM'),
    'is_current_month', v_is_current,
    'days_in_month',    v_days_in,
    'days_elapsed',     v_days,
    'total',            v_total::text,
    'count',            v_count,
    'daily_average',    round(v_total / v_days, 2)::text,

    'biggest', (
      select jsonb_build_object(
               'id', e.id, 'amount', e.amount::text, 'spent_on', e.spent_on,
               'category_name', c.name, 'icon_type', c.icon_type, 'icon_value', c.icon_value)
        from public.expenses e
        join public.categories c on c.id = e.category_id
       where e.user_id = v_uid and e.spent_on between v_month and v_to
       order by e.amount desc, e.spent_on desc, e.created_at desc
       limit 1
    ),

    'prev', jsonb_build_object(
      'month',        to_char(v_prev, 'YYYY-MM'),
      'has_data',     v_prev_count > 0,
      'window_end',   v_window_end,
      'window_total', v_prev_window::text,
      'full_total',   v_prev_full::text
    ),

    'by_category', coalesce((
      select jsonb_agg(jsonb_build_object(
               'category_id', s.id, 'name', s.name,
               'icon_type', s.icon_type, 'icon_value', s.icon_value,
               'total', s.total::text, 'count', s.n)
             order by s.total desc, s.name)
        from (
          select c.id, c.name, c.icon_type, c.icon_value, sum(e.amount) as total, count(*) as n
            from public.expenses e
            join public.categories c on c.id = e.category_id
           where e.user_id = v_uid and e.spent_on between v_month and v_to
           group by c.id, c.name, c.icon_type, c.icon_value
        ) s
    ), '[]'::jsonb),

    'daily', (
      select jsonb_agg(jsonb_build_object('day', x.day, 'total', x.total::text, 'running', x.running::text)
                       order by x.day)
        from (
          select g.i + 1 as day,
                 coalesce(t.total, 0) as total,
                 sum(coalesce(t.total, 0)) over (order by g.i) as running
            from generate_series(0, v_days - 1) as g(i)
            left join (
              select e.spent_on, sum(e.amount) as total
                from public.expenses e
               where e.user_id = v_uid and e.spent_on between v_month and v_to
               group by e.spent_on
            ) t on t.spent_on = v_month + g.i
        ) x
    ),

    'prev_daily', case when v_prev_count = 0 then '[]'::jsonb else (
      select jsonb_agg(jsonb_build_object('day', x.day, 'total', x.total::text, 'running', x.running::text)
                       order by x.day)
        from (
          select g.i + 1 as day,
                 coalesce(t.total, 0) as total,
                 sum(coalesce(t.total, 0)) over (order by g.i) as running
            from generate_series(0, v_prev_days - 1) as g(i)
            left join (
              select e.spent_on, sum(e.amount) as total
                from public.expenses e
               where e.user_id = v_uid and e.spent_on between v_prev and v_prev_end
               group by e.spent_on
            ) t on t.spent_on = v_prev + g.i
        ) x
    ) end,

    'six_months', (
      select jsonb_agg(jsonb_build_object('month', to_char(g.m, 'YYYY-MM'),
                                          'total', coalesce(t.total, 0)::text)
                       order by g.m)
        from generate_series(v_six_from::timestamp, v_month::timestamp, interval '1 month') as g(m)
        left join (
          select date_trunc('month', e.spent_on::timestamp)::date as month, sum(e.amount) as total
            from public.expenses e
           where e.user_id = v_uid and e.spent_on between v_six_from and v_to
           group by 1
        ) t on t.month = g.m::date
    )
  );
end;
$$;

comment on function public.get_month_analytics(date, date) is
  'Spec 04 analytics for one month. security invoker (RLS applies). Money values are text.';

revoke all on function public.get_month_analytics(date, date) from public, anon;
grant execute on function public.get_month_analytics(date, date) to authenticated;
