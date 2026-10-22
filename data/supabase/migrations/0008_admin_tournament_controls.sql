-- Admin controls: restart the online tournament from qualification and manage
-- contestant disqualification without deleting accounts.

create table if not exists public.admin_disqualifications (
  user_id uuid primary key references public.profiles(id) on delete cascade,
  created_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now()
);
alter table public.admin_disqualifications enable row level security;
revoke all on public.admin_disqualifications from public, anon, authenticated;
insert into public.admin_disqualifications(user_id)
  select id from public.profiles where status = 'banned'
  on conflict (user_id) do nothing;

create or replace function public.preserve_admin_disqualification()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if new.status <> 'banned' and exists (
    select 1 from public.admin_disqualifications where user_id = new.id
  ) then
    new.status := 'banned'::public.user_status;
  end if;
  return new;
end $$;
drop trigger if exists profiles_preserve_admin_disqualification on public.profiles;
create trigger profiles_preserve_admin_disqualification
  before update of status on public.profiles
  for each row execute function public.preserve_admin_disqualification();

create or replace function public.admin_reset_tournament_to_entry()
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_state public.tournament_state;
  v_replay_paths jsonb;
  v_jobs int;
begin
  if not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
  end if;

  select * into v_state from public.tournament_state where id = 1 for update;
  if not found then raise exception 'tournament_state_missing'; end if;

  if exists (
    select 1 from public.scoring_jobs
    where status in ('dispatching', 'accepted', 'running')
  ) then
    raise exception 'scoring_jobs_still_running' using errcode = '55000';
  end if;

  select coalesce(jsonb_agg(storage_path), '[]'::jsonb)
    into v_replay_paths from public.replay_objects;

  delete from public.replay_objects;
  delete from public.submissions;
  delete from public.daily_results;
  delete from public.round_byes;
  delete from public.matches;
  delete from public.contest_days;
  delete from public.round_members;
  delete from public.round_advancement;
  delete from public.scoring_jobs;
  get diagnostics v_jobs = row_count;

  update public.profiles
    set status = case when status = 'banned' then 'banned'::public.user_status
                      else 'new'::public.user_status end,
        entry_score = null
    where role = 'contestant';

  update public.tournament_state
    set phase = 'entry', current_round = 0, current_day = 0, pending_day = 0,
        accepting_submissions = true, champion_id = null, updated_at = now()
    where id = 1;

  return jsonb_build_object(
    'status', 'reset',
    'deleted_scoring_jobs', v_jobs,
    'deleted_replay_paths', v_replay_paths,
    'phase', 'entry', 'round', 0, 'day', 0
  );
end $$;
revoke all on function public.admin_reset_tournament_to_entry() from public, anon;
grant execute on function public.admin_reset_tournament_to_entry() to authenticated;

create or replace function public.admin_list_eliminated_contestants()
returns table(id uuid, username text, email text, status public.user_status,
              entry_score numeric, created_at timestamptz, grp int)
language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
  end if;
  return query
    select p.id, p.username, au.email, p.status, p.entry_score, p.created_at,
           rm.grp
    from public.profiles p
    join auth.users au on au.id = p.id
    left join public.round_members rm
      on rm.user_id = p.id
     and rm.rnd = (select current_round from public.tournament_state where id = 1)
    where p.role = 'contestant' and p.status in ('out', 'banned')
    order by case when p.status = 'banned' then 0 else 1 end,
             p.username;
end $$;
revoke all on function public.admin_list_eliminated_contestants() from public, anon;
grant execute on function public.admin_list_eliminated_contestants() to authenticated;

create or replace function public.admin_set_contestant_elimination(
  p_user_id uuid, p_eliminated boolean
)
returns public.user_status
language plpgsql security definer set search_path = public as $$
declare
  v_state public.tournament_state;
  v_profile public.profiles;
  v_status public.user_status;
begin
  if not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
  end if;

  select * into v_state from public.tournament_state where id = 1 for update;
  select * into v_profile from public.profiles where id = p_user_id and role = 'contestant' for update;
  if not found then
    raise exception 'contestant_not_found' using errcode = 'P0002';
  end if;

  if p_eliminated then
    if exists(select 1 from public.matches
        where (player_a = p_user_id or player_b = p_user_id) and state = 'running') then
      raise exception 'contestant_match_running' using errcode = '55000';
    end if;
    -- Prevent a late scoring callback from restoring a disqualified account.
    update public.scoring_jobs set status = 'failed', error_code = 'admin_disqualified',
      error_message = 'Yêu cầu chấm bị hủy do thí sinh bị admin loại.',
      finished_at = now(), updated_at = now()
      where user_id = p_user_id and status in ('dispatching', 'accepted', 'running');
    insert into public.admin_disqualifications(user_id, created_by)
      values (p_user_id, auth.uid()) on conflict (user_id) do nothing;
    update public.profiles set status = 'banned' where id = p_user_id
      returning status into v_status;
    update public.matches set state = 'forfeit', score_a = 0,
      points_a = case when player_a = p_user_id then -1 else 1 end,
      points_b = case when player_b = p_user_id then -1 else 1 end,
      finished_at = now()
      where (player_a = p_user_id or player_b = p_user_id) and state = 'pending';
  else
    delete from public.admin_disqualifications where user_id = p_user_id;
    if v_state.phase = 'entry' then
      v_status := 'new'::public.user_status;
    elsif v_state.phase = 'round' and exists (
      select 1 from public.round_members
      where user_id = p_user_id and rnd = v_state.current_round
    ) then
      v_status := 'active'::public.user_status;
    else
      v_status := 'out'::public.user_status;
    end if;
    update public.profiles set status = v_status where id = p_user_id;
  end if;
  return v_status;
end $$;
revoke all on function public.admin_set_contestant_elimination(uuid, boolean) from public, anon;
grant execute on function public.admin_set_contestant_elimination(uuid, boolean) to authenticated;

-- Storage files are removed through the Storage API after the database reset.
drop policy if exists replay_storage_delete_admin on storage.objects;
create policy replay_storage_delete_admin on storage.objects
  for delete to authenticated using (
    bucket_id = 'replays' and public.is_admin()
  );

-- A manually disqualified contestant must not be requalified by the entry
-- close operation or paired into a later match round.
create or replace function public.admin_close_qualification()
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_qualified int; v_registered int;
begin
  if auth.role() <> 'service_role' and not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
  end if;
  perform 1 from public.tournament_state where id = 1 for update;
  if (select phase from public.tournament_state where id = 1) <> 'entry' then
    raise exception 'entry_phase_required';
  end if;
  if exists(select 1 from public.scoring_jobs where kind = 'entry'
      and status in ('dispatching', 'accepted', 'running')) then
    raise exception 'entry_jobs_still_running';
  end if;
  select count(*) into v_registered from public.profiles where role = 'contestant';
  update public.profiles set status = 'out', entry_score = null
    where role = 'contestant' and status <> 'banned';
  update public.profiles p set entry_score = best.score,
    status = case when best.score >= -2 then 'active'::public.user_status
                  else 'out'::public.user_status end
  from (
    select user_id, max((result ->> 'qualification_score')::numeric) score
    from public.scoring_jobs where kind = 'entry' and status = 'succeeded'
      and result ? 'qualification_score' group by user_id
  ) best where p.id = best.user_id and p.role = 'contestant' and p.status <> 'banned';
  update public.profiles set status = 'out'
    where role = 'contestant' and status = 'new';
  select count(*) into v_qualified from public.profiles
    where role = 'contestant' and status = 'active';
  if v_qualified = 0 then raise exception 'no_qualified_contestants'; end if;

  delete from public.round_members where rnd = 1;
  insert into public.round_members(rnd, user_id, grp, seed)
  with ordered as (
    select id, entry_score,
      row_number() over(order by entry_score desc, id) overall_rank
    from public.profiles where role = 'contestant' and status = 'active'
  ), banded as (
    select *, ceil(overall_rank / 40.0)::int band from ordered
  ), randomized as (
    select *, row_number() over(partition by band order by md5(id::text || ':round-1')) - 1 group_slot
    from banded
  )
  select 1, id, (group_slot % 40)::int, overall_rank::int from randomized;

  insert into public.contest_days(rnd, day, state) values (1, 1, 'open')
    on conflict (rnd, day) do update set state = 'open';
  update public.tournament_state set phase = 'round', current_round = 1,
    current_day = 1, pending_day = 0, accepting_submissions = true, updated_at = now()
    where id = 1;
  return jsonb_build_object('registered', v_registered, 'qualified', v_qualified, 'groups', 40);
end $$;
revoke all on function public.admin_close_qualification() from public, anon;
grant execute on function public.admin_close_qualification() to authenticated, service_role;

create or replace function public.prepare_swiss_round(p_rnd int, p_day int, p_rd int)
returns table(match_id bigint, grp int, player_a uuid, player_b uuid,
              job_a uuid, job_b uuid, match_state text)
language plpgsql security definer set search_path = public as $$
declare
  g record; v_order uuid[]; v_n int; v_half int;
  v_a uuid; v_b uuid; v_i int; v_j int;
begin
  if auth.role() <> 'service_role' and not public.is_admin() then
    raise exception 'admin_required' using errcode = '42501';
  end if;
  if p_rd < 1 or p_rd > 7 then raise exception 'invalid_match_round'; end if;
  if not exists(select 1 from public.contest_days
      where rnd = p_rnd and day = p_day and state in ('open', 'grading')) then
    raise exception 'day_not_open';
  end if;
  if p_rd > 1 and exists(select 1 from public.matches
      where rnd = p_rnd and day = p_day and rd = p_rd - 1
        and state not in ('completed', 'forfeit')) then
    raise exception 'previous_match_round_pending';
  end if;

  for g in select distinct rm.grp from public.round_members rm
      where rm.rnd = p_rnd order by rm.grp loop
    if p_rd = 1 then
      select array_agg(q.user_id order by q.avg_rank, q.seed, q.user_id)
        into v_order from (
          select rm.user_id, rm.seed,
            coalesce((select avg(dr.rank) from public.daily_results dr
              where dr.rnd = rm.rnd and dr.user_id = rm.user_id and dr.day < p_day), 0) avg_rank
          from public.round_members rm
          join public.profiles p on p.id = rm.user_id and p.status <> 'banned'
          where rm.rnd = p_rnd and rm.grp = g.grp
            and (p_day <> 7 or (select count(*) from public.submissions s
              where s.user_id = rm.user_id and s.rnd = p_rnd and s.day between 1 and 6) >= 4)
        ) q;
    else
      select array_agg(q.user_id order by q.points desc, q.avg_rank, q.seed, q.user_id)
        into v_order from (
          select rm.user_id, rm.seed,
            coalesce((select avg(dr.rank) from public.daily_results dr
              where dr.rnd = rm.rnd and dr.user_id = rm.user_id and dr.day < p_day), 0) avg_rank,
            coalesce((select sum(case when m.player_a = rm.user_id then m.points_a else m.points_b end)
              from public.matches m where m.rnd = p_rnd and m.day = p_day and m.rd < p_rd
                and m.state in ('completed', 'forfeit')
                and (m.player_a = rm.user_id or m.player_b = rm.user_id)), 0) points
          from public.round_members rm
          join public.profiles p on p.id = rm.user_id and p.status <> 'banned'
          where rm.rnd = p_rnd and rm.grp = g.grp
            and (p_day <> 7 or (select count(*) from public.submissions s
              where s.user_id = rm.user_id and s.rnd = p_rnd and s.day between 1 and 6) >= 4)
        ) q;
    end if;

    v_n := coalesce(array_length(v_order, 1), 0);
    if v_n = 0 then continue; end if;
    if v_n % 2 = 1 then
      v_a := null;
      for v_i in reverse v_n..1 loop
        if not exists(select 1 from public.round_byes b
            where b.rnd = p_rnd and b.grp = g.grp and b.user_id = v_order[v_i]) then
          v_a := v_order[v_i]; exit;
        end if;
      end loop;
      if v_a is null then v_a := v_order[v_n]; end if;
      insert into public.round_byes(rnd, day, rd, grp, user_id)
        values (p_rnd, p_day, p_rd, g.grp, v_a) on conflict do nothing;
      v_order := array_remove(v_order, v_a);
      v_n := coalesce(array_length(v_order, 1), 0);
      if v_n = 0 then continue; end if;
    end if;

    v_half := v_n / 2;
    if p_rd = 1 then
      for v_i in 1..v_half loop
        v_a := v_order[v_i]; v_b := v_order[v_i + v_half];
        insert into public.matches(rnd, day, rd, grp, player_a, player_b, state)
          values (p_rnd, p_day, p_rd, g.grp, v_a, v_b, 'pending')
          on conflict (rnd, day, rd, player_a, player_b) do nothing;
      end loop;
    else
      while coalesce(array_length(v_order, 1), 0) >= 2 loop
        v_a := v_order[1]; v_b := null;
        for v_j in 2..array_length(v_order, 1) loop
          if not exists(select 1 from public.matches old where old.rnd = p_rnd
              and old.grp = g.grp and old.day = p_day
              and ((old.player_a = v_a and old.player_b = v_order[v_j])
                or (old.player_a = v_order[v_j] and old.player_b = v_a))) then
            v_b := v_order[v_j]; exit;
          end if;
        end loop;
        if v_b is null then v_b := v_order[2]; end if;
        insert into public.matches(rnd, day, rd, grp, player_a, player_b, state)
          values (p_rnd, p_day, p_rd, g.grp, v_a, v_b, 'pending')
          on conflict (rnd, day, rd, player_a, player_b) do nothing;
        v_order := array_remove(array_remove(v_order, v_a), v_b);
      end loop;
    end if;
  end loop;

  return query select m.id, m.grp, m.player_a, m.player_b,
      sa.scoring_job_id, sb.scoring_job_id, m.state
    from public.matches m
    left join public.submissions sa on sa.user_id = m.player_a and sa.rnd = m.rnd and sa.day = m.day
    left join public.submissions sb on sb.user_id = m.player_b and sb.rnd = m.rnd and sb.day = m.day
    where m.rnd = p_rnd and m.day = p_day and m.rd = p_rd order by m.grp, m.id;
end $$;
revoke all on function public.prepare_swiss_round(int, int, int) from public, anon;
grant execute on function public.prepare_swiss_round(int, int, int) to authenticated, service_role;
