-- The online tournament ends after round four. The separately hosted finals
-- application receives qualified contestants through the protected RPC below.
do $$
begin
  if exists (
       select 1 from public.tournament_state
       where current_round = 5 and phase = 'round'
     )
     or exists (select 1 from public.round_members where rnd = 5)
     or exists (select 1 from public.contest_days where rnd = 5)
     or exists (select 1 from public.matches where rnd = 5)
     or exists (select 1 from public.daily_results where rnd = 5)
     or exists (select 1 from public.round_advancement where rnd = 5)
     or exists (select 1 from public.round_byes where rnd = 5)
     or exists (select 1 from public.submissions where rnd = 5)
     or exists (select 1 from public.scoring_jobs where rnd = 5) then
    raise exception 'Cannot remove online round-five configuration while round-five data exists.';
  end if;
end $$;

delete from public.round_config
where rnd = 5;

create or replace function public.admin_list_finalists_for_finals()
returns table (
  user_id uuid,
  username text,
  email text,
  advance_route text,
  final_rank int,
  avg_rank_pct numeric
)
language plpgsql
stable
security definer
set search_path = public
as $$
begin
  if auth.role() <> 'service_role' and not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
  end if;
  if not exists (
    select 1
    from public.tournament_state
    where id = 1 and phase = 'done' and current_round = 4
  ) then
    raise exception 'round_four_not_completed' using errcode = '55000';
  end if;

  return query
  select p.id, p.username, au.email, ra.route::text, ra.final_rank, ra.avg_rank_pct
  from public.round_advancement ra
  join public.profiles p on p.id = ra.user_id
  join auth.users au on au.id = p.id
  where ra.rnd = 4 and ra.route in ('top', 'wildcard')
  order by ra.final_rank, p.username;
end;
$$;

revoke all on function public.admin_list_finalists_for_finals() from public, anon;
grant execute on function public.admin_list_finalists_for_finals() to authenticated, service_role;
