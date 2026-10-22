-- auth.users.email is varchar(255), while the RPC contract exposes text.
-- Cast it explicitly so RETURN QUERY matches the declared result type.
create or replace function public.admin_list_eliminated_contestants()
returns table(id uuid, username text, email text, status public.user_status,
              entry_score numeric, created_at timestamptz, grp int)
language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
  end if;
  return query
    select p.id, p.username, au.email::text, p.status, p.entry_score, p.created_at,
           rm.grp
    from public.profiles p
    join auth.users au on au.id = p.id
    left join public.round_members rm
      on rm.user_id = p.id
     and rm.rnd = (select ts.current_round from public.tournament_state ts where ts.id = 1)
    where p.role = 'contestant' and p.status in ('out', 'banned')
    order by case when p.status = 'banned' then 0 else 1 end,
             p.username;
end $$;

revoke all on function public.admin_list_eliminated_contestants() from public, anon;
grant execute on function public.admin_list_eliminated_contestants() to authenticated;
