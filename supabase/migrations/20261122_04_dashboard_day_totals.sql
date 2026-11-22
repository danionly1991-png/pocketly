-- UI polish: per-day totals for the dashboard's day-grouped expense list ("Today ... Rs 970").
-- A database sum() per day (Spec 03 §7.2); Flask only formats the result.
-- security invoker: RLS on expenses applies as the calling user (auth.uid()).
-- Money is returned as text (exact numeric, never a JSON float).

create or replace function public.dashboard_day_totals(p_from date, p_to date)
returns table (spent_on date, total text)
language sql
stable
security invoker
set search_path = ''
as $$
  select e.spent_on, sum(e.amount)::text
  from public.expenses e
  where e.user_id = (select auth.uid())
    and e.spent_on between p_from and p_to
  group by e.spent_on
  order by e.spent_on desc;
$$;

comment on function public.dashboard_day_totals(date, date) is
  'Dashboard: sum of expenses per day between p_from and p_to. security invoker (RLS applies). Money values are text.';

revoke all on function public.dashboard_day_totals(date, date) from public, anon;
grant execute on function public.dashboard_day_totals(date, date) to authenticated;
